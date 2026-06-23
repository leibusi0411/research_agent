# Save Web Source Snapshots as internal task artifacts

Web Research will save extracted text snapshots for fetched web sources in task files so source text used during the current run remains available locally as an internal artifact. These snapshots are not included in the user-facing Markdown report body.

`WebSource` remains a structured metadata record with `source_id`, `title`, `url`, and `fetched_at`. Full extracted text belongs in Web Source Snapshot files under the task artifacts directory, not in `WebSource`, `ExecutorOutput`, Supervisor prompt context, or the Web Report File body.
