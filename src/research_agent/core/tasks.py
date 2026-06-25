from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from research_agent.core.ids import validate_task_id


VALID_TASK_MODES = {"local", "web"}
VALID_FINISHED_STATUSES = {"completed", "failed"}


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    mode: str
    status: str
    title_or_question: str
    created_at: str
    completed_at: str | None
    report_path: str | None
    result_path: str


class TaskStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)

    def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                  task_id TEXT PRIMARY KEY,
                  mode TEXT NOT NULL CHECK (mode IN ('local', 'web')),
                  status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
                  title_or_question TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  completed_at TEXT,
                  report_path TEXT,
                  result_path TEXT NOT NULL
                )
                """
            )

    def upsert_finished_task(self, record: TaskRecord) -> None:
        validate_task_id(record.task_id)
        if record.mode not in VALID_TASK_MODES:
            raise ValueError(f"invalid task mode: {record.mode}")
        if record.status not in VALID_FINISHED_STATUSES:
            raise ValueError(f"invalid finished task status: {record.status}")

        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                  task_id,
                  mode,
                  status,
                  title_or_question,
                  created_at,
                  completed_at,
                  report_path,
                  result_path
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                  mode = excluded.mode,
                  status = excluded.status,
                  title_or_question = excluded.title_or_question,
                  created_at = excluded.created_at,
                  completed_at = excluded.completed_at,
                  report_path = excluded.report_path,
                  result_path = excluded.result_path
                """,
                (
                    record.task_id,
                    record.mode,
                    record.status,
                    record.title_or_question,
                    record.created_at,
                    record.completed_at,
                    record.report_path,
                    record.result_path,
                ),
            )

    def list_finished_tasks(self) -> list[TaskRecord]:
        self.initialize()
        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                """
                SELECT
                  task_id,
                  mode,
                  status,
                  title_or_question,
                  created_at,
                  completed_at,
                  report_path,
                  result_path
                FROM tasks
                ORDER BY created_at DESC
                """
            ).fetchall()

        return [
            TaskRecord(
                task_id=row["task_id"],
                mode=row["mode"],
                status=row["status"],
                title_or_question=row["title_or_question"],
                created_at=row["created_at"],
                completed_at=row["completed_at"],
                report_path=row["report_path"],
                result_path=row["result_path"],
            )
            for row in rows
        ]
