# Use wide per-tool engineering boundaries for Web tools

V1 Web Research tools use per-call engineering boundaries to prevent individual tool calls from hanging or exhausting local resources. These are not research-strategy limits and do not impose a maximum number of pages per round or per subtask.

V1 performs URL deduplication at the Curator output stage: when multiple `WebSource` records share the same normalized URL, Curator merges them into a single source entry in the final report. Earlier in the pipeline (Tool Gateway, ResearchExecutor), repeated URLs may still create separate `WebSource` records and separate source snapshots to preserve per-subtask traceability; deduplication is deferred to the output boundary rather than enforced at every layer.

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
