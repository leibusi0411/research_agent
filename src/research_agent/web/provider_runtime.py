from __future__ import annotations

import json
from typing import Any

from research_agent.core.errors import ResearchError
from research_agent.core.ids import generate_task_id, utc_now_iso
from research_agent.core.providers import ChatModelClient
from research_agent.core.tasks import TaskRecord, TaskStore
from research_agent.core.workspace import Workspace
from research_agent.web.role_invocation import invoke_role_json


class ProviderBackedWebResearchRuntime:
    def __init__(self, *, workspace: str, chat_model: ChatModelClient) -> None:
        self.workspace = Workspace(workspace)
        self.task_store = TaskStore(self.workspace.root / "tasks.sqlite")
        self.chat_model = chat_model

    def run(self, question: str, task_id: str | None = None) -> dict[str, Any]:
        self.workspace.ensure()
        task_id = task_id or generate_task_id()
        created_at = utc_now_iso()
        self.workspace.create_task_folder(
            task_id,
            task_metadata={"task_id": task_id, "mode": "web", "question": question, "created_at": created_at},
            result={"task_id": task_id, "mode": "web", "question": question, "status": "running"},
        )
        try:
            payload = invoke_role_json(
                role_name="planner",
                prompt=f"Return JSON for web research planning.\nQuestion: {question}",
                target_schema='{"research_title": "string", "subtasks": [{"question": "string"}]}',
                chat_model=self.chat_model,
                validator=_validate_planner_payload,
            )
        except ResearchError as error:
            return self._persist_failed(task_id, question, created_at, error)

        error = ResearchError(
            code="runtime_error",
            message=f"Provider-backed Web Research runtime is not complete yet. Planner returned {len(payload['subtasks'])} subtasks.",
        )
        return self._persist_failed(task_id, question, created_at, error)

    def _persist_failed(self, task_id: str, question: str, created_at: str, error: ResearchError) -> dict[str, Any]:
        result = {
            "task_id": task_id,
            "mode": "web",
            "question": question,
            "status": "failed",
            "created_at": created_at,
            "completed_at": utc_now_iso(),
            "error": error.to_dict(),
        }
        result_path = self.workspace.task_dir(task_id) / "result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        self.task_store.upsert_finished_task(
            TaskRecord(
                task_id=task_id,
                mode="web",
                status="failed",
                title_or_question=question,
                created_at=created_at,
                completed_at=result["completed_at"],
                report_path=None,
                result_path=str(result_path),
            )
        )
        return result


def _validate_planner_payload(payload: dict[str, Any]) -> dict[str, Any]:
    title = payload.get("research_title")
    subtasks = payload.get("subtasks")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("research_title must be a non-empty string")
    if not isinstance(subtasks, list) or not subtasks:
        raise ValueError("subtasks must be a non-empty list")
    for subtask in subtasks:
        if not isinstance(subtask, dict) or not isinstance(subtask.get("question"), str) or not subtask["question"].strip():
            raise ValueError("each subtask must include a non-empty question")
    return payload
