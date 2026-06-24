from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_agent.core.ids import validate_task_id


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    @property
    def tasks_dir(self) -> Path:
        return self.root / "tasks"

    @property
    def local_index_dir(self) -> Path:
        return self.root / "indexes" / "local"

    @property
    def web_reports_dir(self) -> Path:
        return self.root / "reports" / "web"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    def ensure(self) -> None:
        for directory in [
            self.tasks_dir,
            self.local_index_dir,
            self.web_reports_dir,
            self.logs_dir,
        ]:
            directory.mkdir(parents=True, exist_ok=True)

    def task_dir(self, task_id: str) -> Path:
        validate_task_id(task_id)
        return self.tasks_dir / task_id

    def create_task_folder(
        self,
        task_id: str,
        task_metadata: dict[str, Any],
        result: dict[str, Any],
    ) -> Path:
        self.ensure()
        task_dir = self.task_dir(task_id)
        (task_dir / "artifacts" / "web_sources").mkdir(parents=True, exist_ok=True)
        (task_dir / "task.json").write_text(
            json.dumps(task_metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (task_dir / "events.jsonl").touch()
        (task_dir / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return task_dir

    def append_event(self, task_id: str, event: dict[str, Any]) -> None:
        task_dir = self.task_dir(task_id)
        task_dir.mkdir(parents=True, exist_ok=True)
        with (task_dir / "events.jsonl").open("a", encoding="utf-8") as events_file:
            events_file.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
            events_file.write("\n")
