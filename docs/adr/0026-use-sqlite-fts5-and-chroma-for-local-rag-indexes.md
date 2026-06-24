# Use SQLite FTS5 and a local persistent vector index for Local RAG indexes

V1 Local RAG indexing will use SQLite FTS5 for full-text search and a local persistent vector index for vector search. The original design targeted Chroma, but the current Windows development environment exposed two blocking runtime constraints: Chroma 1.x produced native access violations during collection writes, while Chroma 0.5.x required local C++ build tooling for `chroma-hnswlib`. V1 therefore keeps the same rebuildable vector-index boundary but implements it as an application-managed SQLite vector table under `indexes/local/chroma/chroma.sqlite3`. This keeps the local single-user implementation deterministic and testable while preserving a clear adapter point for a future Chroma backend.

Both indexes are built from the same chunk records. Markdown is chunked by heading first and then by paragraphs within each section; plain text, PDF, and HTML use paragraph-based chunking after text extraction. Chunking prefers not to split paragraphs, targets about 3000 characters per chunk, hard-splits only when a single accumulated chunk would exceed about 5000 characters, and uses no fixed overlap. Chunk metadata includes `chunk_id`, `source_path`, `heading_path`, `start_offset`, `end_offset`, and `text`.

`chunk_id` uses an internal stable short-hash form such as `chunk_<short_hash>`, derived from source path, start offset, end offset, mtime, and size.

SQLite FTS5, the local vector index, chunk records, and `manifest.json` are rebuilt together into a temporary location and then swapped into `indexes/local/` only after the whole rebuild succeeds. This prevents a mixed index state where full-text results, vector results, and manifest metadata refer to different chunk sets.
