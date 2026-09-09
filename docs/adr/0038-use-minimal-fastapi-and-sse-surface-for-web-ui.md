# Use a minimal FastAPI and SSE surface for the Web UI

> 演进注记（2026-09-09，R-248）：`GET /api/tasks/{task_id}/events` 实为双模端点——活跃任务走 SSE 流式推送；历史/已完成任务（runtime 已不在注册表且 result 已达终态）直接返回完整事件 JSON 数组（app.py:315-326，注释 "return full events list as JSON — no need for SSE streaming"），前端 `api.ts` 的 taskEvents 已依赖此行为。端点清单自本文后新增 3 个：`GET /api/setup/config`（ADR-0047 已记录）、`POST /api/tasks/{task_id}/deposit`（ADR-0045 已记录）、`DELETE /api/tasks/{task_id}`（R-225 补记于 ADR-0028），当前共 13 个端点。最小化 API 面、仅服务 API 的原则不变。

V1 Web UI talks to the local Core Service through a small FastAPI API surface:

```text
GET  /api/setup/status
POST /api/setup/init

POST /api/research/local
POST /api/research/web
GET  /api/tasks/active
GET  /api/tasks/finished

GET  /api/tasks/{task_id}/events
GET  /api/tasks/{task_id}/result

GET  /api/kb/status
POST /api/kb/rebuild
```

`GET /api/tasks/{task_id}/events` is an SSE endpoint that streams Research Progress Stream records for the requested active or just-finished task. It streams the same phase-based progress objects that CLI renders in-process.

`GET /api/tasks/{task_id}/result` reads the persisted `result.json` for a task. It serves both the current run result page after Local RAG or Web Research completes and the Tasks Page detail view when a finished task row is clicked. The Tasks Page uses `GET /api/tasks/finished` for the summary list and `GET /api/tasks/{task_id}/result` for navigating to a specific task's result page.

The start endpoints return the created `task_id` and mode-specific start state. If another task in the same conflicting task family is already active, the endpoint returns a busy error with the active `task_id` or maintenance operation. V1 does not provide a Web UI Run Both endpoint; users can start Local RAG and Web Research separately.

Setup endpoints only create or report User Config. They do not build indexes, start research, call providers, or start background services. Knowledge Base endpoints expose only status and rebuild.
