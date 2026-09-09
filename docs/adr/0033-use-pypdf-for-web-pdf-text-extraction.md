# Use pypdf for Web PDF text extraction

> 演进注记（2026-09-09，R-232 关联）：pypdf 提取决策本身不变（`tools.py` 中 `web.download_pdf` 仍用 pypdf 提取文本），但"Extracted text is saved as a Web Source Snapshot task artifact"不再成立——与 ADR-0021 同一根因：Web Source Snapshot 只落盘元数据，提取正文仅在内存中进入 Executor 综合 prompt 后即丢弃，不持久化。正文该句已改为现实。

Web Research will use `pypdf` to extract text from PDFs downloaded through `web.download_pdf` in v1. Extracted text is summarized into Findings by ResearchExecutor; only the source metadata (not the extracted text) is saved as a task artifact. V1 only targets basic PDF text extraction; complex layout reconstruction, table extraction, OCR, and high-fidelity rendering are deferred.
