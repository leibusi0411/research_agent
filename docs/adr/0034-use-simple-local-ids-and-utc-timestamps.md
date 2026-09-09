# Use simple local IDs and UTC timestamps

> 演进注记（2026-09-09，R-234）："instead of model-generated identifiers" 及 "runtime assigns src_1/src_2、f_1/f_2" 已被推翻，正文已就地改为现状。现实是 finding_id/source_id 由模型生成——executor 输出 schema 将二者列为必填，解析直接采用模型值，runtime 仅在缺失时兜底 per-subtask 值 `f_{subtask_id}`/`src_{subtask_id}`（src/research_agent/web/executor.py:57-75,149,158）。接受模型生成 ID 的理由：这些 ID 仅作 task-local 展示/引用用途（报告中的 [N] 引用编号由渲染时按 sources 顺序重新编号，不依赖模型值的全局唯一性）；已知风险：同一 ID 跨 subtask 可能重复，v1 接受该风险。仍成立的部分：task_id（`task_yyyymmdd_hhmmss_<random6>`）、subtask_id（st_N）、chunk_<short_hash> 由 runtime 分配；所有持久化时间戳为 UTC ISO 8601 带 `Z` 后缀。另：原文 "the Curator output stage merges duplicates for the final report" 不存在于代码，v1 任何阶段都不做 URL 去重（与 ADR-0031 一致），正文已一并修正。

V1 uses simple local IDs and UTC ISO 8601 timestamps instead of distributed IDs. Runtime assigns IDs where global consistency matters (`task_id`, `subtask_id`, chunk IDs); finding and source IDs are model-generated with runtime fallbacks (see below).

All persisted timestamps use UTC ISO 8601 with `Z`, for example `2026-06-23T10:30:00Z`. This applies to fields such as `created_at`, `updated_at`, `started_at`, `completed_at`, `fetched_at`, and `built_at`. UI may render local time, but storage and APIs use UTC.

`task_id` uses `task_yyyymmdd_hhmmss_<random6>`, for example `task_20260623_103000_a1b2c3`, and is used as the task artifact directory name under `tasks/`.

Within one Web Research task, IDs work as follows:

- `subtask_id`: `st_1`, `st_2`, and so on. Plan Revision appends new subtasks using the next available number; IDs are not reused or reordered.
- `source_id`: model-generated per executor output; runtime falls back to `src_{subtask_id}` when the model omits a value. V1 does not deduplicate URLs at any stage, so repeated URLs may receive separate source IDs and appear as separate entries in the final report.
- `finding_id`: model-generated per executor output; runtime falls back to `f_{subtask_id}` when the model omits a value. Curator does not create new findings.

Local RAG chunk IDs use a stable short-hash form such as `chunk_<short_hash>`, derived from source path, start offset, end offset, mtime, and size. Chunk IDs are internal index identifiers and are not intended as user-facing labels.
