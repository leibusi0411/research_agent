from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from research_agent.core.chroma_store import ChromaStore
from research_agent.core.config import load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.kb import KnowledgeBaseIndex
from research_agent.core.providers import ChatModelClient, EmbeddingClient, RerankClient
from research_agent.core.tasks import TaskRecord, TaskStore
from research_agent.core.workspace import Workspace

logger = logging.getLogger(__name__)


def run_local_research(
    *,
    question: str,
    workspace: Workspace,
    task_store: TaskStore,
    config_path: Path | None,
    task_id: str | None = None,
    embedding_client: EmbeddingClient | None = None,
    chat_model: ChatModelClient | None = None,
    rerank_client: RerankClient | None = None,
) -> dict[str, Any]:
    task_id = task_id or generate_task_id()
    created_at = utc_now_iso()
    kb_index = KnowledgeBaseIndex(workspace, config_path)
    status = kb_index.status()["status"]
    # "stale" means FTS5 is fresh but Chroma vectors may be out of date —
    # keyword search is still usable.
    if status not in ("ready", "stale"):
        error = _index_status_error(status)
        result = _failed_result(task_id, question, created_at, error)
        _persist_task(workspace, task_store, task_id, question, created_at, result)
        return result

    # Emit progress: retrieval started
    workspace.append_event(
        task_id,
        {
            "task_id": task_id,
            "mode": "local",
            "phase": "local_rag",
            "event_type": "progress",
            "created_at": utc_now_iso(),
            "message": "Searching local knowledge base...",
            "details": {"items": []},
        },
    )

    queries = [question]
    # ADR-0052 (evolution 2026-09-16): the [chat_model.local_summarizer]
    # section is the switch — present → Multi-Query rewriting active, absent →
    # the question runs as-is; LLM failure degrades to the original question
    # alone (rewrite_question returns []).
    config = load_user_config(config_path)
    if "local_summarizer" in config.role_chat_models and chat_model is not None:
        queries.extend(rewrite_question(question, chat_model))

    query_result_lists = [
        retrieve_local_chunks(
            sqlite_path=workspace.local_index_dir / "fts.sqlite",
            chroma_path=workspace.local_index_dir.parent / "chroma",
            question=query,
            embedding_client=embedding_client,
            rerank_client=rerank_client,
        )
        for query in queries
    ]
    local_results = rrf_fuse(query_result_lists, top_k=10)

    # A+G: Augment prompt with retrieved chunks + generate answer via LLM
    summary: str | None = None
    if chat_model is not None and local_results:
        workspace.append_event(
            task_id,
            {
                "task_id": task_id,
                "mode": "local",
                "phase": "local_rag",
                "event_type": "progress",
                "created_at": utc_now_iso(),
                "message": "Generating summary from retrieved chunks...",
                "details": {"items": []},
            },
        )
        summary = _generate_summary(question, local_results, chat_model)

    completed_at = utc_now_iso()

    # Build source items for completed event
    source_items: list[dict[str, Any]] = []
    for r in local_results:
        source_items.append({
            "kind": "source",
            "path": r.get("source_path", ""),
            "title": r.get("source_path", ""),
        })
    result = {
        "task_id": task_id,
        "mode": "local",
        "question": question,
        "status": "completed",
        "created_at": created_at,
        "completed_at": completed_at,
        "local_results": local_results,
    }
    if summary is not None:
        result["summary"] = summary
    _persist_task(workspace, task_store, task_id, question, created_at, result, completed_items=source_items, result_count=len(local_results))
    return result


# ---------------------------------------------------------------------------
# Query rewrite (ADR-0052)
# ---------------------------------------------------------------------------

# Default Multi-Query variant budget: one keyword-extraction style plus one
# semantic-descriptive style variant.
_REWRITE_MAX_VARIANTS = 2

_VARIANT_PREFIX_RE = re.compile(r"^\s*(?:\d+\s*[.、)：:)]\s*|[-*•·]\s+)")
_VARIANT_QUOTES = "\"“”'「」『』"


def rewrite_question(
    question: str,
    chat_model: ChatModelClient,
    *,
    max_variants: int = _REWRITE_MAX_VARIANTS,
) -> list[str]:
    """Rewrite *question* into Multi-Query retrieval variants (ADR-0052).

    One LLM call asks for a keyword-extraction variant and a semantic-
    descriptive variant. Lines are cleaned of numbering, bullets, and
    quotes; blanks, duplicates, and restatements of the original question
    are dropped; the result is capped at *max_variants*. Any LLM failure
    degrades to ``[]`` — the caller falls back to the original question
    only, so rewriting never blocks Local RAG.
    """
    prompt = (
        "你是一个检索查询改写助手。请把下面的用户问题改写成 "
        f"{max_variants} 个用于知识库检索的查询变体：\n"
        "1. 一个关键词式变体：只保留核心检索词，用空格分隔；\n"
        "2. 一个语义式变体：用一句完整的陈述句换一种说法表达同一信息需求。\n"
        "每行输出一个变体，不要编号，不要解释。\n\n"
        f"用户问题：{question}"
    )
    try:
        raw = chat_model.complete(prompt)
    except Exception as exc:
        logger.warning("Query rewrite failed; falling back to the original question: %s", exc)
        return []

    variants: list[str] = []
    seen: set[str] = {question.strip().lower()}
    for line in raw.splitlines():
        cleaned = _VARIANT_PREFIX_RE.sub("", line).strip().strip(_VARIANT_QUOTES).strip()
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        variants.append(cleaned)
        if len(variants) >= max_variants:
            break
    return variants


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
    fts_query = " ".join(f'"{term}"' for term in terms)

    try:
        with closing(sqlite3.connect(sqlite_path)) as connection:
            connection.row_factory = sqlite3.Row
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
        source_path = row["source_path"]
        start_offset = row["start_offset"]
        end_offset = row["end_offset"]
        results.append(
            {
                "chunk_id": f"{source_path}:{start_offset}:{end_offset}",
                "text": row["text"],
                "source_path": source_path,
                "heading_path": json.loads(row["heading_path"]),
                "start_offset": start_offset,
                "end_offset": end_offset,
                "score": None,  # R-63: normalize with Chroma results (FTS5 has no score)
            }
        )
    return results


def rrf_fuse(
    result_lists: list[list[dict[str, Any]]],
    *,
    top_k: int | None,
    k: int = 60,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion across ranked result lists (ADR-0052).

    Shared by single-question hybrid retrieval and Multi-Query fusion: each
    list contributes ``1 / (k + rank)`` to the chunk keyed by
    ``source_path:start:end``; the first-seen record wins for display, and
    the fused order is truncated to *top_k* (``None`` keeps every chunk).
    """
    rrf_scores: dict[str, float] = {}
    result_map: dict[str, dict[str, Any]] = {}
    for results in result_lists:
        for rank, item in enumerate(results, start=1):
            key = _dedup_key(item)
            rrf_scores[key] = rrf_scores.get(key, 0) + 1.0 / (k + rank)
            if key not in result_map:
                result_map[key] = item
    ranked_keys = sorted(rrf_scores, key=lambda key: rrf_scores[key], reverse=True)
    return [result_map[key] for key in ranked_keys[:top_k]]


def _apply_rerank(
    fused: list[dict[str, Any]],
    *,
    question: str,
    top_k: int,
    rerank_client: RerankClient | None,
) -> list[dict[str, Any]]:
    """Reorder *fused* by reranker relevance (ADR-0053).

    Applies only when a client is configured and the candidate set exceeds
    the display budget — reordering a list that is returned whole buys
    nothing.  A rerank failure or an incomplete ordering degrades to the
    RRF order, symmetric with the Chroma→FTS5-only degradation.
    """
    if rerank_client is None or len(fused) <= top_k:
        return fused
    try:
        pairs = rerank_client.rerank(question, [item["text"] for item in fused])
        indices = [index for index, _score in pairs]
        if sorted(indices) != list(range(len(fused))):
            logger.warning("Rerank returned an incomplete ordering; keeping RRF order")
            return fused
        return [fused[index] for index in indices]
    except Exception as exc:
        logger.warning("Rerank failed; falling back to RRF order: %s", exc)
        return fused


def retrieve_local_chunks(
    *,
    sqlite_path: Path,
    chroma_path: Path,
    question: str,
    embedding_client: EmbeddingClient | None = None,
    top_k: int = 10,
    rerank_client: RerankClient | None = None,
) -> list[dict[str, Any]]:
    """Hybrid retrieval: FTS5 keyword + Chroma vector search with RRF fusion.

    Public seam shared by Local RAG, the Web Research Prior Knowledge
    retriever (ADR-0046), and the Planner local survey (ADR-0048). Falls
    back gracefully to FTS5-only when no embedding_client is available
    (e.g. in tests or when the embedding model isn't configured). When a
    rerank_client is provided and candidates exceed *top_k*, a cross-encoder
    reorders the fused list before truncation (ADR-0053).
    """
    # Fetch more candidates than needed so RRF has enough to fuse
    fetch_k = top_k * 2

    fts5_results = _search_fts5(sqlite_path, question, top_k=fetch_k)

    chroma_results: list[dict[str, Any]] = []
    if embedding_client is not None:
        query_embedding = embedding_client.embed([question])[0]
        store = ChromaStore(chroma_path)
        try:
            chroma_results = store.query(query_embedding, n_results=fetch_k)
        finally:
            store.close()

    if not fts5_results and not chroma_results:
        return []

    fused = rrf_fuse([fts5_results, chroma_results], top_k=None)
    fused = _apply_rerank(fused, question=question, top_k=top_k, rerank_client=rerank_client)
    return fused[:top_k]


def _dedup_key(item: dict[str, Any]) -> str:
    return f"{item.get('source_path', '')}:{item.get('start_offset', 0)}:{item.get('end_offset', 0)}"


# ---------------------------------------------------------------------------
# FTS5 query helpers
# ---------------------------------------------------------------------------

# Characters that FTS5 interprets as operators or syntax.  Stripping them
# from user queries avoids syntax errors on inputs like "C++" or "(async)".
_FTS5_SPECIAL_RE = re.compile(r'[\(\)\*\"\+\\\-\^\{\}\[\]~!@#\$%^&:,;<>?/|]+')


def _fts5_terms(question: str) -> list[str]:
    """Split *question* into safe, non-empty FTS5 search terms."""
    sanitized = _FTS5_SPECIAL_RE.sub(" ", question).replace("'", " ")
    return [t.strip() for t in sanitized.split() if t.strip()]


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
    *,
    completed_items: list[dict[str, Any]] | None = None,
    result_count: int = 0,
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
    message = result["status"]
    if result_count:
        message = f"{result['status']} — {result_count} results"
    workspace.append_event(
        task_id,
        {
            "task_id": task_id,
            "mode": "local",
            "phase": "local_rag",
            "event_type": "completed",
            "created_at": utc_now_iso(),
            "message": message,
            "details": {"items": completed_items or []},
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
    # Emit task_result event so SSE consumers can stop polling and fetch the result once.
    workspace.append_event(
        task_id,
        {
            "task_id": task_id,
            "mode": "local",
            "phase": "local_rag",
            "event_type": "task_result",
            "created_at": utc_now_iso(),
            "message": f"Task {result['status']}.",
            "details": {"items": [{"kind": "status", "task_id": task_id, "status": result["status"], "mode": "local"}]},
        },
    )


# ---------------------------------------------------------------------------
# Augmentation + Generation
# ---------------------------------------------------------------------------


def _build_augmented_prompt(
    question: str,
    chunks: list[dict[str, Any]],
    top_n: int = 10,
) -> str:
    """Build an augmented prompt with retrieved chunks as reference material."""
    context_parts: list[str] = []
    for i, chunk in enumerate(chunks[:top_n], 1):
        source = chunk.get("source_path", "unknown")
        heading = " > ".join(chunk.get("heading_path", [])) or "(无标题)"
        text = chunk.get("text", "")
        context_parts.append(
            f"[{i}] 来源: {source}\n    标题: {heading}\n    {text}"
        )
    context = "\n\n".join(context_parts)
    return (
        "你是一个个人知识库助手。请根据以下参考资料回答用户问题。\n"
        "只使用参考资料中的信息，如果信息不足请明确指出。\n"
        "回答时请引用对应的参考编号（如 [1]、[2]）。\n\n"
        f"参考资料：\n\n{context}\n\n"
        f"用户问题：{question}\n\n"
        "请用中文回答："
    )


def _generate_summary(
    question: str,
    chunks: list[dict[str, Any]],
    chat_model: ChatModelClient,
) -> str:
    """Augment prompt with chunks and generate answer via LLM."""
    prompt = _build_augmented_prompt(question, chunks)
    return chat_model.complete(prompt)
