# Use function-call tools with Registry, Gateway, and Runner

Web Research tool calls use a standard function-call shape and pass through an internal Tool Registry, Tool Gateway, and Tool Runner. V1 registers only `web.search`, `web.fetch_extract`, and `web.download_pdf`; before execution, Tool Gateway must verify that the tool exists, arguments match the tool input schema, and the Web Research workflow is allowed to use the tool. Only validated calls are handed to Tool Runner. `web.download_pdf` uses pypdf for text extraction after download. Tool implementations return a unified `ToolResult` with `status`, `data`, optional `error`, and optional `metadata`; Local RAG and Knowledge Base Indexing do not use this agent tool path in v1.

Per-call timeout, response-size, PDF-size, search result count, and retry boundaries are engineering protections, not research-strategy limits. V1 does not perform URL normalization or URL deduplication.
