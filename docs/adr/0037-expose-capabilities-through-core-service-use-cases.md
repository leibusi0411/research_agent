# Expose capabilities through Core Service use cases

> 演进注记（2026-09-09，R-239）：用例面已扩大——CoreService 新增了三个清单外 public 方法：`run_local_research_unlocked`、`run_web_research_unlocked`、`acquire_family_lock`（core/service.py:173/184/345）。同时"薄适配器"原则在 API 层的后台任务编排上被有意打破：FastAPI 层自行实现任务创建（`_create_running_task` 直写 task.json/初始 result.json/首条 "Task started." 事件，app.py:450-468）、族锁生命周期编排（主线程 acquire + 后台线程释放，app.py:471-523），并绕过带锁用例直调上述 unlocked 方法。这是 R-110/R-114 等一系列并发修复积累出的架构现状。CLI 仍是薄适配器；下文 Core Service 跨切关注点清单仍然成立。

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
