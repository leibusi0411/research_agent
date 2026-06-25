from __future__ import annotations

from typing import Any

from research_agent.core.providers import ChatModelClient
from research_agent.core.workspace import Workspace
from research_agent.web.state_graph import StateGraphRunner
from research_agent.web.tools import ToolGateway


class ProviderBackedWebResearchRuntime:
    def __init__(
        self,
        *,
        workspace: str,
        chat_model: ChatModelClient,
        tool_gateway: ToolGateway,
        max_retrieval_rounds: int = 3,
        max_concurrent_subtasks: int = 3,
        on_event: Any | None = None,
    ) -> None:
        self.workspace = Workspace(workspace)
        self.chat_model = chat_model
        self.tool_gateway = tool_gateway
        self.max_retrieval_rounds = max_retrieval_rounds
        self.max_concurrent_subtasks = max_concurrent_subtasks
        self.on_event = on_event

    def run(self, question: str, task_id: str | None = None) -> dict[str, Any]:
        runner = StateGraphRunner(
            workspace=str(self.workspace.root),
            chat_model=self.chat_model,
            tool_gateway=self.tool_gateway,
            max_retrieval_rounds=self.max_retrieval_rounds,
            max_concurrent_subtasks=self.max_concurrent_subtasks,
            on_event=self.on_event,
        )
        return runner.run(question, task_id)
