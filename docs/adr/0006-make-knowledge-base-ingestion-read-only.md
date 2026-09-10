# Make Knowledge Base Ingestion read-only by default

> 演进注记（2026-09-10）：分块与检索文本策略已由 ADR-0049（Chunking v2）显式演进——目标块大小 3000→1000 字符、超长段落滑窗 10% 重叠、新增 `search_text`（heading_path + tags + wikilinks 前缀）同时进入 FTS5 与向量索引。本 ADR 的只读边界与轻量解析决策不变。

Knowledge Base Ingestion reads a user-configured Markdown Vault, parses frontmatter, titles, headings, links, chunks, file metadata, and content, then builds full-text and vector indexes for Local RAG. It must not rewrite existing notes, move files, reorganize directories, add tags, delete duplicates, merge notes, or modify frontmatter in v1 because the Markdown Vault is the user's long-term canonical knowledge source.

V1 Local ingestion uses lightweight Markdown parsing for frontmatter, headings, Markdown links, and wikilinks rather than rendering Markdown to HTML. Plain text files are read directly. Local PDF text extraction uses `pypdf`, and local HTML text extraction uses `trafilatura`, reusing the same extraction dependencies selected for Web Research. V1 defers OCR, complex PDF layout reconstruction, table extraction, high-fidelity rendering, and complex DOM preservation.

V1 chunks Markdown by heading first, then groups paragraphs within each section. Plain text, PDF, and HTML sources use paragraph-based chunking after text extraction. Chunking prefers not to split paragraphs, targets about 3000 characters per chunk, hard-splits only when a single accumulated chunk would exceed about 5000 characters, and uses no fixed overlap. Each chunk records `chunk_id`, `source_path`, `heading_path`, `start_offset`, `end_offset`, and `text`.
