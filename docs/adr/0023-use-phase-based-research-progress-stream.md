# Use phase-based Research Progress Stream records

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

Each line in `tasks/{task_id}/events.jsonl` is one JSON object with top-level fields: `task_id`, `mode`, `phase`, `event_type`, optional `event_subtype`, `created_at`, `message`, `seq`, and `details`. `mode` is `local` or `web`. `event_type` is `started`, `progress`, `completed`, or `failed`. V1 does not add `event_id` or an outer `subtask_id`; subtask context, if useful for display, belongs in `message` or `details`.

`event_subtype` (added 2026-06-30) is an optional field that classifies `progress`-scoped events for direct UI rendering without parsing `details.items`. Values: `tool_call`, `finding`, `source`, `subtask_started`, `subtask_completed`, `subtask_failed`. Phase-boundary events (`started`, `completed`, `failed`) omit `event_subtype`. CLI uses it to select output format; Web UI uses it to pick the appropriate detail card.

`seq` (added 2026-06-30, renamed from `_seq` on 2026-07-02 per R-112) is a monotonically increasing integer assigned by `_emit`. Consumers use it for deduplication when the EventStream replays persisted events from `events.jsonl` before switching to live queue consumption.

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

Tool calls are represented as phase progress details rather than separate top-level progress records. Report paths are carried on the `web_curation` phase's `completed` record. This keeps Web UI and CLI rendering consistent without exposing LangGraph internals or proliferating progress categories.
