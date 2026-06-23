# Use a minimal FastAPI and SSE surface for the Web UI

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
