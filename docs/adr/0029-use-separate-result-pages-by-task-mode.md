# Use separate result pages by task mode

V1 Web UI result views are separated by task mode for the current task result after a run completes. Local RAG tasks show a Local Result Page with relevant content and source file paths, while Web Research tasks show a Web Report Page with progress, summary, findings, sources, and `report_path`. Finished task rows in the Web UI Tasks Page navigate to the corresponding result page by calling `GET /api/tasks/{task_id}/result` and rendering the mode-appropriate result view (Local Result Page or Web Report Page).

Current result pages are read-only views over stored task records. They read persisted Local Results, Research Progress records, CuratorOutput, source metadata, `report_path`, or failure errors. Opening the current result page does not rerun Local RAG retrieval, does not resume Web Research, does not call tools, does not regenerate CuratorOutput, and does not rewrite the Web Report File.

The Local Result Page displays:

- `question`
- `status`
- Local Results, each with `text` and `source_path`
- `heading_path` when available and useful for orientation

The Web Report Page displays:

- `question`
- `status`
- Process View grouped by phase, using progress `message` values and minimal `details.items`
- Summary from CuratorOutput
- Findings from CuratorOutput
- Sources from CuratorOutput
- `report_path` when the Web Report File was written successfully
- `file_write_error` when CuratorOutput succeeded but report writing failed

If report file writing fails after CuratorOutput succeeds, the Web Report Page shows the task status as `failed` with `file_write_error` instead of showing a completed task without a report. There is no combined comparison page in v1.
