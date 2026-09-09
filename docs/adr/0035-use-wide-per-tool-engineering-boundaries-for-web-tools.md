# Use wide per-tool engineering boundaries for Web tools

> 演进注记（2026-09-09，R-247）：原文 "V1 performs URL deduplication at the Curator output stage" 一段与 ADR-0031（"V1 does not perform URL normalization or URL deduplication"）互相矛盾，且代码与 prompt 中均不存在该机制（`graph.py` 原样拷贝 sources、`prompt_builders.py` 无去重指令、全 src 无 URL 去重）。经审查裁定以代码为准、站在 ADR-0031 一侧：v1 不做 URL 归一化或去重，同 URL 的源在最终报告中保持多条。正文该段已按此改写。本 ADR 的其余边界值（timeout 45/90、大小上限、`search_top_k` 10/20、`tool_retries` 2）均已兑现，不受影响。

V1 Web Research tools use per-call engineering boundaries to prevent individual tool calls from hanging or exhausting local resources. These are not research-strategy limits and do not impose a maximum number of pages per round or per subtask.

V1 does not perform URL normalization or URL deduplication at any stage (consistent with ADR-0031): `WebSource` records that share the same URL remain separate entries throughout the pipeline and in the final report. Repeated URLs may create separate `WebSource` records and separate source snapshots to preserve per-subtask traceability.

Default boundaries are intentionally wide:

```toml
[web_tools]
request_timeout_seconds = 45
pdf_timeout_seconds = 90
max_response_bytes = 20971520
max_pdf_bytes = 104857600
search_top_k = 10
search_top_k_max = 20
tool_retries = 2
```

`web.search` accepts a query string, uses the configured search provider, defaults to `search_top_k = 10`, and allows at most `search_top_k_max = 20` results for one call. This is a per-call return-size boundary, not a total research limit.

`web.fetch_extract` accepts `http` and `https` URLs, applies `request_timeout_seconds`, rejects responses larger than `max_response_bytes`, accepts HTML, XHTML, and plain-text-like content, and extracts text with `trafilatura` when HTML is present.

`web.download_pdf` accepts `http` and `https` URLs, applies `pdf_timeout_seconds`, rejects files larger than `max_pdf_bytes`, expects PDF content or a PDF-looking URL, and extracts text with `pypdf`.

Tool errors are normalized as `validation_error`, `transient_error`, or `permanent_error`. Tool Gateway retries same-parameter `transient_error` results up to `tool_retries`; ResearchExecutor handles strategic recovery such as changing query, changing URL, skipping a source, or returning Subtask Failure.
