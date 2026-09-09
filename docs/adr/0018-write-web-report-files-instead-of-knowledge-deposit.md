# Write Web Report Files instead of Knowledge Base deposit in v1

> 演进注记（2026-09-09，R-245）：ADR-0045 已引入应用内 Knowledge Deposit（`core/deposit.py`、CLI `task deposit`、API `POST /api/tasks/{task_id}/deposit`、Web UI 按钮），用户可以在应用内把 Web 报告显式沉淀进 vault。本 ADR 的核心仍然成立：报告首先写成 `reports/web/` 下的 Markdown 文件，沉淀是事后显式动作而非自动；变的只是"用户在应用外自行决定"这一限定（正文未改）。

V1 will not automatically deposit research outputs into the Markdown Vault. Web Research tasks write a local Markdown Web Report File under `reports/web/` with summary, findings, linked evidence, and the full web source list, while Local RAG tasks display existing local content with source paths; users decide outside the application whether and how to save web reports into their knowledge system. Workflow-internal research gaps are not included in the Web Report File.

After CuratorOutput is produced successfully, runtime immediately renders the Markdown template and writes the Web Report File to `reports/web/`. Web Research is marked `completed` only after the Web Report File is written successfully. Web UI displays `report_path`, and CLI prints `report_path` when the command completes. If writing the report file fails, the task is marked `failed` with a `file_write_error` because the user-visible report file was not created. Task list views still display only summary fields and do not add a separate report artifact column.
