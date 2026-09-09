# Allow Local RAG and Web Research to run independently

V1 keeps Local RAG and Web Research as independent task modes with separate runtime paths. A user may run only Local RAG, only Web Research, or start both for the same question as separate tasks. Local RAG and Web Research may run concurrently because Web Research does not read Local RAG indexes or Local Results, and Local RAG does not call Web Research tools.

> 演进注记（2026-09-06）：ADR-0046 引入了一个例外——Web Research 图启动前会对 `indexes/local/` 做一次一次性、只读的 Prior Knowledge 检索注入 Planner。它只读派生索引、不调用 Local RAG 流程，因此本 ADR 的并发结论不受影响。

> 演进注记（2026-09-09，R-252）：kb rebuild 与 Local RAG 的互斥只实现了一半，且语义与下文描述不同。正向：`kb rebuild` 只写 `local.building` 标记（core/kb.py:130-132），不检查 local 族任务锁——Local RAG 运行中照样可以 rebuild。反向：Local RAG 撞上 `building` 状态时，不返回 busy 错误，而是生成一个失败任务结果，错误码 `kb_index_building`（core/local_research.py:35-39、240-251）。仍然成立的部分：rebuild 不是 Research Task、不阻塞 Web Research；同族任务锁（local / web 各一）与下文其余并发结论不变。CONTEXT.md 已按此行为改写。

Concurrency is limited by task family, not globally:

- Only one Local RAG task runs at a time.
- Only one Web Research task runs at a time.
- One Local RAG task and one Web Research task may run at the same time.
- One Web Research task may still execute multiple Supervisor-selected subtasks concurrently through ResearchExecutor, bounded by `research.max_concurrent_subtasks`.

Knowledge Base index rebuild is not a Research Task and does not block Web Research. It conflicts only with Local RAG because Local RAG reads `indexes/local/` while rebuild writes and swaps those indexes. Therefore, `kb rebuild` and Local RAG are mutually exclusive; `kb rebuild` and Web Research may run concurrently.

If a second task in the same conflicting family is requested, CLI returns a busy error with the active `task_id` or maintenance operation, and Web UI disables only the conflicting start action. V1 does not queue tasks automatically; task queues and broader multi-task execution are future upgrades.
