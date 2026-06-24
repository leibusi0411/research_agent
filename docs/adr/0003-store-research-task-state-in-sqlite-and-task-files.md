# Store task lists in SQLite and task results in local files

V1 stores all task data locally on the user's computer under the configured Default Workspace. SQLite stores structured task-list fields, while per-task files store result-display data and larger artifacts. Each task gets a task directory containing `task.json`, `events.jsonl`, `result.json`, and mode-specific artifacts. SQLite stores list/query fields such as `task_id`, `mode`, `status`, `title_or_question`, `created_at`, `completed_at`, and `report_path` when available. Task files store richer data used by the current run result view.

V1 uses one core SQLite task table:

```sql
CREATE TABLE tasks (
  task_id TEXT PRIMARY KEY,
  mode TEXT NOT NULL CHECK (mode IN ('local', 'web')),
  status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
  title_or_question TEXT NOT NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT,
  report_path TEXT,
  result_path TEXT NOT NULL
);
```

`created_at` and `completed_at` use UTC ISO 8601 with `Z`. `result_path` points to `tasks/{task_id}/result.json`. V1 task history records only finished tasks, so SQLite stores a task after it reaches `completed` or `failed`; running-task visibility comes from active runtime state and task-local files, not from task-history rows. V1 does not implement checkpoint-based task recovery or orphaned running-task repair. V1 does not create a `progress_events` SQLite table; progress records are written only to `events.jsonl`. Each `events.jsonl` line is an append-only Research Progress Stream JSON object and is used for display, not routing or final report generation.

Local RAG tasks persist the task record, progress records, final status, and the returned Local Results with source paths in `result.json`. Web Research tasks persist the task record, progress records, final status, CuratorOutput, source metadata, and `report_path` when Web Report File writing succeeds in `result.json`; extracted Web source text is stored under `artifacts/web_sources/`. The user-visible Web Report File is written only under `reports/web/`, not duplicated inside the task artifact directory.

If Web Report File writing fails after CuratorOutput is produced, the Web Research task is `failed` with a `file_write_error`. V1 treats the report file as the user-visible Web Research output, so a task must not be recorded as `completed` with `report_path: null`.

Local `result.json` uses this shape:

```json
{
  "task_id": "task_20260623_103000_a1b2c3",
  "mode": "local",
  "question": "LangGraph deep research architecture",
  "status": "completed",
  "created_at": "2026-06-23T10:30:00Z",
  "completed_at": "2026-06-23T10:30:05Z",
  "local_results": [
    {
      "text": "Relevant content excerpt",
      "source_path": "D:/vault/langgraph.md",
      "heading_path": ["Agent", "LangGraph"],
      "start_offset": 120,
      "end_offset": 430
    }
  ]
}
```

Failed Local tasks replace `local_results` with `error`, using the unified Research Error object.

Web `result.json` uses this shape:

```json
{
  "task_id": "task_20260623_103000_d4e5f6",
  "mode": "web",
  "question": "LangGraph deep research architecture",
  "status": "completed",
  "created_at": "2026-06-23T10:30:00Z",
  "completed_at": "2026-06-23T10:35:00Z",
  "curator_output": {
    "title": "LangGraph Deep Research Architecture",
    "summary": "...",
    "findings": [],
    "sources": []
  },
  "report_path": "D:/ResearchAgent/reports/web/langgraph-deep-research-2026-06-23.md"
}
```

If Web Research fails before CuratorOutput, `result.json` stores `status: "failed"` and `error`, using the unified Research Error object. If CuratorOutput succeeds but report writing fails, `result.json` also stores `status: "failed"` and `error` with `code: "file_write_error"`. It must not store a completed Web task with `report_path: null`.

`result.json` does not store full Web source text, raw tool results, full prompts, model completions, executor scratchpads, or the full progress event list. Progress records belong in `events.jsonl`, and extracted Web source text belongs under `artifacts/web_sources/`.
