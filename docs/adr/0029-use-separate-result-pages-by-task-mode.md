# Use separate result pages by task mode

V1 Web UI result views are separated by task mode for the current task result after a run completes. Local RAG tasks show a Local Result Page with relevant content and source file paths, while Web Research tasks show a Web Report Page with progress, summary, findings, sources, and `report_path`. Finished task rows in the Web UI Tasks Page expand an inline detail card directly below the clicked row, calling `GET /api/tasks/{task_id}/result` and rendering the mode-appropriate result view (Local Result View or Web Report View) without route navigation.

> 演进注记（2026-09-09，R-246）：Tasks 页点击任务行不再跳转独立结果页路由，而是行内展开详情卡片（web/src/pages/TasksPage.tsx:46-55，2026-09-09 工作区改动，REVIEW_TRACKER R-224）；App.tsx 路由表仅有 `/`、`/tasks`、`/kb`、`/settings`。正文对应句已按现实修订。按模式分离的结果视图（Local Result View / Web Report View）保留不变，本 ADR 其余内容（只读视图、各视图字段、file_write_error 展示、无合并对比页）仍然成立。

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
