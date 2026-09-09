# Save Web Source Snapshots as internal task artifacts

> 演进注记（2026-09-09，R-232）：核心决策已失效。现实是：`_save_source_snapshots`（`state_graph.py`）只写 `source.to_dict()` 元数据（`source_id`/`title`/`url`/`fetched_at` 四字段，见 `schemas.py` 的 `WebSource`），提取正文只在内存中进入 Executor 综合 prompt 后即被丢弃，全代码无任何位置持久化正文——"source text used during the current run remains available locally" 不成立。负面清单（正文不进 `WebSource`/`ExecutorOutput`/Supervisor prompt/报告正文）仍然成立。若未来实现阶段 8 的 Source 快照查看器，需要重新决策正文持久化。正文已改为现实。

Web Research saves a metadata record (`source_id`, `title`, `url`, `fetched_at`) per fetched web source under the task artifacts directory (`artifacts/web_sources/<source_id>.json`); the full extracted text is used only in-memory during the run and is not persisted. These metadata snapshots are not included in the user-facing Markdown report body.

`WebSource` remains a structured metadata record with `source_id`, `title`, `url`, and `fetched_at`. Full extracted text stays out of `WebSource`, `ExecutorOutput`, Supervisor prompt context, and the Web Report File body.
