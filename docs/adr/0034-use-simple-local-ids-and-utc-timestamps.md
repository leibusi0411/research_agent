# Use simple local IDs and UTC timestamps

V1 uses simple local IDs and UTC ISO 8601 timestamps instead of distributed IDs or model-generated identifiers.

All persisted timestamps use UTC ISO 8601 with `Z`, for example `2026-06-23T10:30:00Z`. This applies to fields such as `created_at`, `updated_at`, `started_at`, `completed_at`, `fetched_at`, and `built_at`. UI may render local time, but storage and APIs use UTC.

`task_id` uses `task_yyyymmdd_hhmmss_<random6>`, for example `task_20260623_103000_a1b2c3`, and is used as the task artifact directory name under `tasks/`.

Within one Web Research task, runtime assigns sequential local IDs:

- `subtask_id`: `st_1`, `st_2`, and so on. Plan Revision appends new subtasks using the next available number; IDs are not reused or reordered.
- `source_id`: `src_1`, `src_2`, and so on. V1 does not deduplicate URLs during execution, so repeated URLs may receive separate source IDs; the Curator output stage merges duplicates for the final report.
- `finding_id`: `f_1`, `f_2`, and so on. Curator does not create new findings.

Local RAG chunk IDs use a stable short-hash form such as `chunk_<short_hash>`, derived from source path, start offset, end offset, mtime, and size. Chunk IDs are internal index identifiers and are not intended as user-facing labels.
