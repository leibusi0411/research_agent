# Use simple human-readable CLI output

V1 CLI output is human-readable first and uses the same Core Service results, Research Progress Stream records, and Research Error objects as Web UI. It does not need a machine-readable JSON output mode in v1.

> 演进注记（2026-09-09，R-238、R-255）：两处输出规格未兑现，正文对应句已按现实修订。① `research-agent local` 不流式显示 `local_rag` 进度——local 为同步调用，`run_local_research` 无 on_event 参数（src/research_agent/core/service.py:134），`both` 的 local 侧同样静默（根因同 R-238，见 ADR-0011 演进注记）。② `research-agent kb rebuild` 无进度输出——cli.py:126-135 同步跑完后只打印与 `kb status` 相同的 5 个键。其余输出规格（`[code] message`、非零退出、both 分区段、task list 摘要字段、无 JSON 模式、无 task show/delete、无 kb update/clean/delete）均已兑现，不变。

`research-agent local "question"`:

- Runs synchronously without streaming `local_rag` progress; output prints when the task completes.
- On success, prints the top Local Results. Each result shows relevant text and `source_path`; optional heading/path offsets may be shown if useful.
- On failure, prints `[code] message` from the Research Error and exits non-zero.

`research-agent web "question"`:

- Streams Web Research phases: `web_planning`, `web_execution`, `web_supervision`, `web_revision`, and `web_curation`.
- On success, prints Summary, Findings, Sources, and `report_path`.
- If CuratorOutput succeeds but Web Report File writing fails, marks the Web Research task failed, prints `[file_write_error] message`, and exits non-zero.
- On failure before CuratorOutput, prints `[code] message` from the Research Error and exits non-zero.

`research-agent both "question"`:

- Starts separate Local RAG and Web Research tasks for the same question.
- Displays separate Local and Web progress sections.
- Prints both final outputs independently.
- Exits `0` only when both tasks complete successfully and the Web Report File is written successfully.
- Exits non-zero if either task fails, including Web Report File writing failure, while still showing any successful task output.

`research-agent task list`:

- Prints all finished tasks with `task_id`, `mode`, `status`, `title_or_question`, and `created_at`.
- Does not show task detail, `error_summary`, report file errors, or delete prompts in v1.

`research-agent kb status`:

- Prints index `status`, `vault_path`, `file_count`, `chunk_count`, and `last_indexed_at` when available.

`research-agent kb rebuild`:

- Runs synchronously without progress output; on success, prints the same keys as `kb status` (including final `file_count` and `chunk_count`).
- On failure, prints `[code] message` from the Research Error and exits non-zero.
