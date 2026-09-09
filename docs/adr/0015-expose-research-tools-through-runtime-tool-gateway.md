# Expose Web Research tools through a runtime Tool Gateway

> 演进注记（2026-09-09，R-250）：原文把 "call recording" 列为 Tool Gateway 集中的职责之一，与代码不符。现实：`ToolGateway.call`（`web/tools.py`）只做工具存在性/权限/参数校验与同参数 transient 重试，自身无任何记录；调用记录实际分散在 executor 层的进度事件流（`web/executor.py` → `events.jsonl`）与 `llm_calls` 工件。记录存在，但不在 Gateway 集中；正文已删去 "call recording" 一词。其余职责（注册、权限检查、重试、结构化结果）仍然成立。

Web Research will call Web Search, Web Fetch Extract, Web PDF Download, and related agent tools through a Tool Gateway rather than embedding those implementations directly. The Tool Gateway centralizes tool registration, workflow permission checks, same-parameter low-level retries, and structured tool results; Local RAG and Knowledge Base Indexing remain fixed Core Service flows and are not registered as agent tools.
