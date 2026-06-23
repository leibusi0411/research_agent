# Use Markdown for Web Report Files

V1 Web Research report files are Markdown files written under `reports/web/`. Local RAG tasks show existing local knowledge as source-linked results but do not produce a Web Report File; Web report filenames use the research topic and date, structured JSON may exist internally as task state or debug data, and PDF, HTML, DOCX, and richer publishing formats are deferred.

Runtime writes the Markdown file immediately after successful CuratorOutput generation. Web Research is marked `completed` only after the Markdown file is written successfully. A file write failure marks the Web Research task `failed` with `file_write_error`, leaves `report_path` unavailable, and makes the CLI command exit non-zero.

Report files use `{topic_slug}-{yyyy-mm-dd}.md`. The slug is derived from the user question or report title, preserves Chinese characters, lowercases English letters, replaces whitespace with hyphens, removes Windows-illegal filename characters (`<>:"/\|?*`), truncates to 80 characters, and appends `-2`, `-3`, and so on when a file already exists.
