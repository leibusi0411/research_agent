from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from research_agent.core.chroma_store import ChromaStore
from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.kb import KnowledgeBaseIndex
from research_agent.core.providers import EmbeddingClient
from research_agent.core.tasks import TaskRecord, TaskStore
from research_agent.core.workspace import Workspace


def run_local_research(
    *,
    question: str,
    workspace: Workspace,
    task_store: TaskStore,
    config_path: Path | None,
    task_id: str | None = None,
    embedding_client: EmbeddingClient | None = None,
) -> dict[str, Any]:
    task_id = task_id or generate_task_id()
    created_at = utc_now_iso()
    kb_index = KnowledgeBaseIndex(workspace, config_path)
    status = kb_index.status()["status"]
    if status != "ready":
        error = _index_status_error(status)
        result = _failed_result(task_id, question, created_at, error)
        _persist_task(workspace, task_store, task_id, question, created_at, result)
        return result

    local_results = _retrieve_hybrid(
        sqlite_path=workspace.local_index_dir / "fts.sqlite",
        chroma_path=workspace.local_index_dir.parent / "chroma",
        question=question,
        embedding_client=embedding_client,
    )
    completed_at = utc_now_iso()
    result = {
        "task_id": task_id,
        "mode": "local",
        "question": question,
        "status": "completed",
        "created_at": created_at,
        "completed_at": completed_at,
        "local_results": local_results,
    }
    _persist_task(workspace, task_store, task_id, question, created_at, result)
    return result


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def _search_fts5(
    sqlite_path: Path,
    question: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """FTS5 keyword search over indexed chunks (fixes R-13).

    Sanitises user input by stripping FTS5 special characters and quoting
    each term so that reserved words (AND, OR, NOT, NEAR) and punctuation
    like ``C++`` or ``(async)`` don't cause syntax errors.
    """
    terms = _fts5_terms(question)
    if not terms:
        return []

    # Quote every term so reserved words / special chars are literal.
    # Implicit AND between terms gives better precision than OR on
    # typical user questions.
    fts_query = " ".join(
        f'"{term}"' if " " not in term else _fts5_phrase(term) for term in terms
    )

    try:
        with sqlite3.connect(sqlite_path) as connection:
            rows = connection.execute(
                """
                SELECT c.source_path, c.heading_path, c.start_offset, c.end_offset, c.text
                FROM chunks_fts fts
                JOIN chunks c ON c.chunk_id = fts.chunk_id
                WHERE chunks_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (fts_query, top_k),
            ).fetchall()
    except sqlite3.OperationalError:
        return []

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append(
            {
                "text": row[4],
                "source_path": row[0],
                "heading_path": json.loads(row[1]),
                "start_offset": row[2],
                "end_offset": row[3],
            }
        )
    return results


def _retrieve_hybrid(
    *,
    sqlite_path: Path,
    chroma_path: Path,
    question: str,
    embedding_client: EmbeddingClient | None = None,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """Hybrid retrieval: FTS5 keyword + Chroma vector search with RRF fusion.

    Falls back gracefully to FTS5-only when no embedding_client is available
    (e.g. in tests or when the embedding model isn't configured).
    """
    # Fetch more candidates than needed so RRF has enough to fuse
    fetch_k = top_k * 2

    fts5_results = _search_fts5(sqlite_path, question, top_k=fetch_k)

    chroma_results: list[dict[str, Any]] = []
    if embedding_client is not None:
        query_embedding = embedding_client.embed([question])[0]
        store = ChromaStore(chroma_path)
        chroma_results = store.query(query_embedding, n_results=fetch_k)
        store.close()

    if not fts5_results and not chroma_results:
        return []

    # Reciprocal Rank Fusion (k=60 is the standard constant)
    K = 60
    rrf_scores: dict[str, float] = {}
    result_map: dict[str, dict[str, Any]] = {}

    for rank, item in enumerate(fts5_results, start=1):
        key = _dedup_key(item)
        rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (K + rank)
        result_map[key] = item

    for rank, item in enumerate(chroma_results, start=1):
        key = _dedup_key(item)
        rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (K + rank)
        if key not in result_map:
            result_map[key] = item

    ranked_keys = sorted(rrf_scores, key=lambda k: rrf_scores[k], reverse=True)
    return [result_map[key] for key in ranked_keys[:top_k]]


def _dedup_key(item: dict[str, Any]) -> str:
    return f"{item.get('source_path', '')}:{item.get('start_offset', 0)}:{item.get('end_offset', 0)}"


# ---------------------------------------------------------------------------
# FTS5 query helpers
# ---------------------------------------------------------------------------

# Characters that FTS5 interprets as operators or syntax.  Stripping them
# from user queries avoids syntax errors on inputs like "C++" or "(async)".
_FTS5_SPECIAL_RE = __import__("re").compile(r'[\(\)\*\"\+\\\-\^\{\}\[\]~!@#\$%^&:,;<>?/|]+')

# FTS5 reserved words that must be quoted to be treated as literal terms.
_FTS5_RESERVED = frozenset({"AND", "OR", "NOT", "NEAR"})


def _fts5_terms(question: str) -> list[str]:
    """Split *question* into safe, non-empty FTS5 search terms."""
    sanitized = _FTS5_SPECIAL_RE.sub(" ", question).replace("'", " ")
    return [t.strip() for t in sanitized.split() if t.strip()]


def _fts5_phrase(term: str) -> str:
    """Wrap a multi-word term as an FTS5 phrase, escaping internal quotes."""
    escaped = term.replace('"', '""')
    return f'"{escaped}"'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _index_status_error(status: str) -> ResearchError:
    code_by_status = {
        "missing": "kb_index_missing",
        "stale": "kb_index_stale",
        "building": "kb_index_building",
        "failed": "kb_index_failed",
    }
    code = code_by_status.get(status, "kb_index_failed")
    return ResearchError(
        code=code,
        message=f"Local RAG index is {status}. Run research-agent kb rebuild before local research.",
    )


def _failed_result(
    task_id: str,
    question: str,
    created_at: str,
    error: ResearchError,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "mode": "local",
        "question": question,
        "status": "failed",
        "created_at": created_at,
        "completed_at": utc_now_iso(),
        "error": error.to_dict(),
    }


def _persist_task(
    workspace: Workspace,
    task_store: TaskStore,
    task_id: str,
    question: str,
    created_at: str,
    result: dict[str, Any],
) -> None:
    task_dir = workspace.create_task_folder(
        task_id,
        task_metadata={
            "task_id": task_id,
            "mode": "local",
            "question": question,
            "created_at": created_at,
        },
        result=result,
    )
    workspace.append_event(
        task_id,
        {
            "task_id": task_id,
            "mode": "local",
            "phase": "local_rag",
            "event_type": "completed",
            "created_at": utc_now_iso(),
            "message": result["status"],
            "details": {"items": []},
        },
    )
    task_store.upsert_finished_task(
        TaskRecord(
            task_id=task_id,
            mode="local",
            status=result["status"],
            title_or_question=question,
            created_at=created_at,
            completed_at=result.get("completed_at"),
            report_path=None,
            result_path=str(task_dir / "result.json"),
        )
    )
