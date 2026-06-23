# Expose capabilities through Core Service use cases

V1 exposes product behavior through a small Core Service use-case surface shared by CLI and Web UI:

- `init_config(...)`
- `run_local_research(question)`
- `run_web_research(question)`
- `run_both(question)`
- `list_finished_tasks()`
- `get_kb_status()`
- `rebuild_kb_index()`

CLI commands and FastAPI endpoints are thin interface adapters over these use cases. They should not implement separate task creation, concurrency control, progress emission, result persistence, Local RAG retrieval, Web Research routing, report writing, or Knowledge Base indexing behavior.

`run_both(question)` is a Core Service convenience used by CLI only in v1. It starts one Local RAG task and one Web Research task for the same question, keeps their progress and results separate, and does not create a parent task, combined workflow, combined report, or shared context.

The Core Service owns these cross-cutting responsibilities:

- Load and validate User Config.
- Resolve the Default Workspace.
- Enforce active task-family locks and `kb rebuild` conflicts.
- Create task IDs and task directories.
- Append Research Progress Stream records.
- Persist task history and `result.json`.
- Coordinate Web Report File writing after Web Curator output.
- Return interface-neutral result and error objects for CLI and Web UI rendering.

This keeps the Capability Surface consistent across interfaces while still allowing CLI and Web UI to provide different presentation helpers.
