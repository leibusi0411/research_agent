# Allow Local RAG and Web Research to run independently

V1 keeps Local RAG and Web Research as independent task modes with separate runtime paths. A user may run only Local RAG, only Web Research, or start both for the same question as separate tasks. Local RAG and Web Research may run concurrently because Web Research does not read Local RAG indexes or Local Results, and Local RAG does not call Web Research tools.

> 演进注记（2026-09-06）：ADR-0046 引入了一个例外——Web Research 图启动前会对 `indexes/local/` 做一次一次性、只读的 Prior Knowledge 检索注入 Planner。它只读派生索引、不调用 Local RAG 流程，因此本 ADR 的并发结论不受影响。

Concurrency is limited by task family, not globally:

- Only one Local RAG task runs at a time.
- Only one Web Research task runs at a time.
- One Local RAG task and one Web Research task may run at the same time.
- One Web Research task may still execute multiple Supervisor-selected subtasks concurrently through ResearchExecutor, bounded by `research.max_concurrent_subtasks`.

Knowledge Base index rebuild is not a Research Task and does not block Web Research. It conflicts only with Local RAG because Local RAG reads `indexes/local/` while rebuild writes and swaps those indexes. Therefore, `kb rebuild` and Local RAG are mutually exclusive; `kb rebuild` and Web Research may run concurrently.

If a second task in the same conflicting family is requested, CLI returns a busy error with the active `task_id` or maintenance operation, and Web UI disables only the conflicting start action. V1 does not queue tasks automatically; task queues and broader multi-task execution are future upgrades.
