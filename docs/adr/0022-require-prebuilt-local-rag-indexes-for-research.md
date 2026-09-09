# Require prebuilt Local RAG indexes for research

> 演进注记（2026-09-09，R-229）：`failed` 状态语义已扩大。现在只要 vector 产物文件（`indexes/chroma/chroma.sqlite3`）缺失即判 `failed`（core/kb.py:92-93），Local RAG 随即拒绝查询（core/local_research.py:35）——即使 FTS5 索引完全可用。该行为已被测试固化（tests/test_kb_index.py:121-135）。下方 2026-07-03 update 中 "`stale` indicates FTS5 is usable" 仅在 vector 文件存在、仅内容过时时成立；Chroma 构建失败且 vector 文件缺失时，状态是 `failed` 而非 `stale`（注意 `rebuild()` 的即时返回值此时仍报 `"stale"`，core/kb.py:174，与随后的 `kb status` 结果不一致）。已知取舍：Chroma 构建失败后 FTS5 虽在，但 Local RAG 整体不可用，直到下一次完整 rebuild 成功。

> 演进注记（2026-09-09，R-244）：部署机制已部分改变。FTS5 部分仍是临时目录构建 + 原子替换（`_atomic_swap_fts5`，core/kb.py:146-147、197-211）；但 Chroma 向量索引已移出 `indexes/local/`，独立放在 `indexes/chroma/`（core/kb.py:72-80，见 R-243：Windows 上 HNSW segment 文件持有内存映射锁，阻止父目录原子重命名），其部署是 `shutil.copytree(chroma_tmp, self.chroma_dir, dirs_exist_ok=True)` 合并拷贝（core/kb.py:159）——非原子，且旧 segment 文件残留不清理。因此文末 "Only after all build steps succeed does runtime atomically replace `indexes/local/`" 一句只对 FTS5 成立，不再描述整体部署。

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
