# Require prebuilt Local RAG indexes for research

Local RAG retrieval depends on prebuilt Knowledge Base indexes. Index rebuilding is an explicit maintenance action through CLI or Web UI, not automatic large-scale work inside a local task; if indexes are missing or stale, the Local RAG task fails and tells the user to rebuild the index before retrying. V1 stale detection compares indexed file path, mtime, and size before running Local RAG.

V1 CLI exposes only `research-agent kb status` and `research-agent kb rebuild`. It does not include `kb update`, `kb clean`, `kb delete`, or `kb inspect`.

`kb status` returns one of five states:

- `missing`: no usable Local RAG index exists.
- `ready`: indexes exist and the manifest matches the configured source files by path, mtime, and size.
- `stale`: indexes exist, but files were added, removed, or changed by path, mtime, or size.
- `building`: an index rebuild is currently running.
- `failed`: the last rebuild failed and no usable prior index exists.

Local RAG queries run when status is `ready` or `stale` (FTS5 keyword index is available even if ChromaDB vectors are outdated). For `missing`, `building`, or `failed`, `research-agent local` fails before retrieval and tells the user to run `research-agent kb rebuild`.

> **2026-07-03 update**: Status check relaxed from `ready`-only to `ready`|`stale` per R-131. ChromaDB build failures no longer roll back the FTS5 index, so `stale` indicates FTS5 is usable.

`kb rebuild` builds into a temporary index location first, including SQLite FTS5 data, Chroma data, chunk records, and a manifest. Only after all build steps succeed does runtime atomically replace `indexes/local/`. If rebuild fails while a prior index exists, the prior index is preserved and status remains `stale` rather than `failed`; Local RAG still refuses to query until a successful rebuild. `failed` is reserved for cases where no usable prior index exists.
