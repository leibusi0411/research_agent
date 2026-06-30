from __future__ import annotations

from typing import Any

from research_agent.core.providers import ChatModelClient
from research_agent.core.tasks import TaskStore
from research_agent.core.workspace import Workspace
from research_agent.web.state_graph import StateGraphRunner
from research_agent.web.tools import ToolGateway


class ProviderBackedWebResearchRuntime:
    def __init__(
        self,
        *,
        workspace: str,
        chat_models: dict[str, ChatModelClient],
        tool_gateway: ToolGateway,
        max_retrieval_rounds: int = 3,
        max_concurrent_subtasks: int = 3,
        on_event: Any | None = None,
        workspace_obj: Workspace | None = None,
        task_store: TaskStore | None = None,
    ) -> None:
        # R-24: Accept optional pre-existing Workspace/TaskStore to reduce
        # duplicate instances in the call chain.
        self._workspace_obj = workspace_obj if workspace_obj is not None else Workspace(workspace)
        self._task_store = task_store
        self.chat_models = chat_models
        self.tool_gateway = tool_gateway
        self.max_retrieval_rounds = max_retrieval_rounds
        self.max_concurrent_subtasks = max_concurrent_subtasks
        self.on_event = on_event
        self.runner: StateGraphRunner | None = None

    def run(self, question: str, task_id: str | None = None) -> dict[str, Any]:
        self.runner = StateGraphRunner(
            workspace=str(self._workspace_obj.root),
            chat_models=self.chat_models,
            tool_gateway=self.tool_gateway,
            max_retrieval_rounds=self.max_retrieval_rounds,
            max_concurrent_subtasks=self.max_concurrent_subtasks,
            on_event=self.on_event,
            workspace_obj=self._workspace_obj,
            task_store=self._task_store,
        )
        return self.runner.run(question, task_id)
