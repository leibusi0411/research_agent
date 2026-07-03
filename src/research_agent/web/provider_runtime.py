from __future__ import annotations

from typing import Any

from research_agent.web.state_graph import RunnerConfig, StateGraphRunner


class ProviderBackedWebResearchRuntime:
    def __init__(
        self,
        *,
        config: RunnerConfig,
    ) -> None:
        # R-24: Accept optional pre-existing Workspace/TaskStore to reduce
        # duplicate instances in the call chain.
        self._config = config
        self.runner: StateGraphRunner | None = None

    def run(self, question: str, task_id: str | None = None) -> dict[str, Any]:
        self.runner = StateGraphRunner(config=self._config)
        return self.runner.run(question, task_id)
