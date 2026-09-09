# Use phase-based Research Progress Stream records

> 演进注记（2026-09-09，R-236/R-242）：事件契约较本文有所扩展，且传输层已替换。(1) R-236 契约扩展：`event_type` 在四值白名单（`started|progress|completed|failed`）外实际还发射 `task_result`（把最终结果直接推给订阅层，已收进 `web/schemas.py` 的 `Literal`；API 层 SSE 超时另发临时串 `stream_timeout`，未进任何类型定义）；`event_subtype` 集合多出 `research_gap`；`details.items` 的 `kind` 除 `tool_call`/`source`/`finding` 外还有 `status`。"每行 `events.jsonl` 都含 `seq`、由 `_emit` 分配"不再成立：Local 模式的全部事件（`core/local_research.py`）与 API 层写入的 started 事件（`api/app.py`）不经过 `_emit`、没有 `seq` 字段，消费端对缺失 `seq` 做容忍（`evt.get("seq", -1)`）。(2) R-242 传输层替换：janus.Queue 的 EventStream 已被 asyncio 实现的 `Bus` 取代（`core/bus.py`：每订阅者一个 `asyncio.Queue`、默认容量 1024、满时丢弃并 warning、发布方可从工作线程跨 loop 投递），janus 依赖随之移除；replay-then-live（先重放 `events.jsonl` 再切实时队列 + seq 去重）的语义保留在 `state_graph.py`。仍然成立：phase 划分、`event_type` 四值主体语义、`details.items` 展示专用（不作恢复/路由/监督/报告的事实源）的定位不变。

Research progress streaming is phase-based rather than based on global progress categories. Each streamed record represents progress for one product-level phase and has `phase` as its primary discriminator. `event_type` only describes the progress state inside that phase: `started`, `progress`, `completed`, or `failed`.

Local RAG and Web Research are separate workflows, so their phases are separate in practice. Local RAG uses `local_rag`. Web Research uses `web_planning`, `web_execution`, `web_supervision`, `web_revision`, and `web_curation`. `web_planning` is the first Planner run that creates the initial subtask plan, while `web_revision` is a later Planner run that appends new pending subtasks based on Supervisor-maintained research gaps.

V1 progress records use this shape:

```json
{
  "task_id": "task_20260623_abc123",
  "mode": "web",
  "phase": "web_execution",
  "event_type": "progress",
  "event_subtype": "tool_call",
  "created_at": "2026-06-23T10:30:00Z",
  "message": "Searching for LangGraph core concepts",
  "seq": 42,
  "details": {
    "items": []
  }
}
```

Each line in `tasks/{task_id}/events.jsonl` is one JSON object with top-level fields: `task_id`, `mode`, `phase`, `event_type`, optional `event_subtype`, `created_at`, `message`, optional `seq`, and `details`. `mode` is `local` or `web`. `event_type` is `started`, `progress`, `completed`, or `failed`, plus `task_result` (see the evolution note above) which pushes the final result directly to subscribers. V1 does not add `event_id` or an outer `subtask_id`; subtask context, if useful for display, belongs in `message` or `details`.

`event_subtype` (added 2026-06-30) is an optional field that classifies `progress`-scoped events for direct UI rendering without parsing `details.items`. Values: `tool_call`, `finding`, `source`, `subtask_started`, `subtask_completed`, `subtask_failed`, `research_gap`. Phase-boundary events (`started`, `completed`, `failed`) omit `event_subtype`. CLI uses it to select output format; Web UI uses it to pick the appropriate detail card.

`seq` (added 2026-06-30, renamed from `_seq` on 2026-07-02 per R-112) is a monotonically increasing integer assigned by `_emit`. Events written outside `_emit` — all Local RAG events and the API-layer `started` record — carry no `seq`, and consumers tolerate its absence. Consumers use it for deduplication when the stream replays persisted events from `events.jsonl` before switching to live queue consumption.

`details.items` is display-only and is not used as the source of truth for recovery, routing, Supervisor judgment, or final report generation. Internal state remains authoritative. `events.jsonl` is an append-only progress display log, is not inserted into SQLite, and is not used as a Supervisor or Curator input.

`details.items` stays minimal and supports only these v1 item shapes:

```json
{ "kind": "tool_call", "name": "web.search", "input": "LangGraph deep research architecture" }
```

```json
{ "kind": "source", "title": "LangGraph documentation", "url": "https://langchain-ai.github.io/langgraph/" }
```

```json
{ "kind": "source", "path": "D:/vault/langgraph.md" }
```

```json
{ "kind": "finding", "text": "LangGraph supports stateful graph workflows." }
```

```json
{ "kind": "status", "text": "Research complete." }
```

Tool calls are represented as phase progress details rather than separate top-level progress records. Report paths are carried on the `web_curation` phase's `completed` record. This keeps Web UI and CLI rendering consistent without exposing LangGraph internals or proliferating progress categories.
