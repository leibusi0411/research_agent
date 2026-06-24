from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.kb import KnowledgeBaseIndex
from research_agent.core.tasks import TaskRecord, TaskStore
from research_agent.core.workspace import Workspace


def run_local_research(
    *,
    question: str,
    workspace: Workspace,
    task_store: TaskStore,
    config_path: Path | None,
    task_id: str | None = None,
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

    local_results = _retrieve_local_results(workspace.local_index_dir / "fts.sqlite", question)
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


def _retrieve_local_results(sqlite_path: Path, question: str) -> list[dict[str, Any]]:
    terms = [term.lower() for term in question.split() if term.strip()]
    with sqlite3.connect(sqlite_path) as connection:
        rows = connection.execute(
            """
            SELECT source_path, heading_path, start_offset, end_offset, text
            FROM chunks
            """
        ).fetchall()
    ranked = sorted(
        rows,
        key=lambda row: _score(row[4], terms),
        reverse=True,
    )
    results: list[dict[str, Any]] = []
    for source_path, heading_path, start_offset, end_offset, text in ranked:
        if terms and _score(text, terms) == 0:
            continue
        results.append(
            {
                "text": text,
                "source_path": source_path,
                "heading_path": json.loads(heading_path),
                "start_offset": start_offset,
                "end_offset": end_offset,
            }
        )
        if len(results) >= 10:
            break
    return results


def _score(text: str, terms: list[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(term) for term in terms)


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
        task_metadata={"task_id": task_id, "mode": "local", "question": question, "created_at": created_at},
        result=result,
    )
    workspace.append_event(task_id, {"phase": "local_rag", "event_type": "completed", "message": result["status"]})
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
