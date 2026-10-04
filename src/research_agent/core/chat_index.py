"""Task-local retrieval index for grounded chat (R-285, ADR-0057).

Each research task gets its own index directory —
``tasks/{task_id}/chat_index/`` — physically isolated from the global
Knowledge Base index (``indexes/``): separate FTS5 database, separate
Chroma collection, own lifecycle (deleted with the task). Imported
sources' original fetched text (``artifacts/source_texts/``) is chunked
and embedded **into this task index only**; the vault KB never sees web
content, and deposit remains the only bridge into it.

Indexing is append-only and idempotent: ``imports.json`` records which
source ids have been built, so re-imports are no-ops and new imports
extend the index incrementally. No chat model is involved — chunking is
plain code, embeddings go to the embedding API.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

from research_agent.core.local_research import rrf_fuse

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1200
_CHUNK_OVERLAP = 200
_RETRIEVE_TOP_K = 6
_EMBED_BATCH = 64


class TaskChatIndex:
    """Owns ``tasks/{task_id}/chat_index/``: import bookkeeping, chunking,
    embeddings, and hybrid (FTS5 + vector) retrieval over imported sources."""

    def __init__(self, task_dir: Path, embedding_client: Any) -> None:
        self.task_dir = Path(task_dir)
        self.embedding_client = embedding_client
        self.index_dir = self.task_dir / "chat_index"
        self._imports_path = self.index_dir / "imports.json"
        self._fts_path = self.index_dir / "fts.sqlite"

    # ── import bookkeeping ──────────────────────────────────────────────

    def _load_imports(self) -> dict[str, Any]:
        if not self._imports_path.exists():
            return {"sources": {}}
        try:
            return json.loads(self._imports_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"sources": {}}

    def _save_imports(self, imports: dict[str, Any]) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self._imports_path.write_text(json.dumps(imports, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── build (append-only) ─────────────────────────────────────────────

    def build_imports(self, result: dict[str, Any], source_ids: list[str]) -> None:
        """Index the original text of newly imported sources. Already-built
        source ids are skipped; nothing here touches the global KB index."""
        curator = result.get("curator_output") or {}
        sources = {s.get("source_id"): s for s in curator.get("sources", []) if isinstance(s, dict)}
        imports = self._load_imports()
        dirty = False
        for source_id in source_ids:
            if source_id in imports["sources"]:
                continue
            source = sources.get(source_id)
            if not source:
                continue
            text = self._load_source_text(str(source.get("url", "")))
            if not text.strip():
                logger.info("No fetched original text for %s (%s); metadata-only grounding", source_id, source.get("url"))
                continue
            self._index_source(str(source_id), str(source.get("url", "")), str(source.get("title", "")), text)
            imports["sources"][source_id] = {"url": source.get("url", ""), "chars": len(text)}
            dirty = True
        if dirty:
            self._save_imports(imports)

    def _load_source_text(self, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        path = self.task_dir / "artifacts" / "source_texts" / f"{digest}.txt"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    # ── indexing ────────────────────────────────────────────────────────

    def _chunk(self, text: str) -> list[str]:
        chunks: list[str] = []
        start = 0
        step = _CHUNK_SIZE - _CHUNK_OVERLAP
        while start < len(text):
            chunks.append(text[start : start + _CHUNK_SIZE])
            start += step
        return chunks or [""]

    def _index_source(self, source_id: str, url: str, title: str, text: str) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        chunks = self._chunk(text)
        vectors: list[list[float]] = []
        # Batch the embedding calls: a very long source yields hundreds of
        # chunks and one request would blow the API body limit.
        for i in range(0, len(chunks), _EMBED_BATCH):
            vectors.extend(self.embedding_client.embed(chunks[i : i + _EMBED_BATCH]))
        ids = [f"{source_id}::{i}" for i in range(len(chunks))]
        self._fts_insert(ids, source_id, url, title, chunks)
        self._chroma_upsert(ids, source_id, url, title, chunks, vectors)

    def _fts_insert(self, ids: list[str], source_id: str, url: str, title: str, chunks: list[str]) -> None:
        with sqlite3.connect(self._fts_path) as conn:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(chunk_id UNINDEXED, source_id UNINDEXED, url UNINDEXED, title UNINDEXED, text)"
            )
            # Idempotent under the build race: clear any rows these chunk ids
            # already own, then insert fresh (FTS5 has no unique constraint).
            conn.executemany(
                "DELETE FROM chunks WHERE chunk_id = ?",
                [(cid,) for cid in ids],
            )
            conn.executemany(
                "INSERT INTO chunks (chunk_id, source_id, url, title, text) VALUES (?, ?, ?, ?, ?)",
                [(cid, source_id, url, title, chunk) for cid, chunk in zip(ids, chunks)],
            )

    def _chroma_upsert(self, ids: list[str], source_id: str, url: str, title: str, chunks: list[str], vectors: list[list[float]]) -> None:
        try:
            import chromadb

            client = chromadb.PersistentClient(path=str(self.index_dir / "chroma"))
            collection = client.get_or_create_collection("chat_index")
            collection.upsert(
                ids=ids,
                embeddings=vectors,
                documents=chunks,
                metadatas=[{"source_id": source_id, "url": url, "title": title}] * len(chunks),
            )
        except Exception:
            # Vector search is an enhancement; FTS5 alone still works (ADR-0022
            # degrade semantics). Index build must not fail the chat turn.
            logger.warning("Chat index vector upsert failed; FTS5-only for this source", exc_info=True)

    # ── retrieval ───────────────────────────────────────────────────────

    def retrieve(self, query: str, source_ids: list[str], top_k: int = _RETRIEVE_TOP_K) -> list[dict[str, Any]]:
        """Hybrid retrieval restricted to *source_ids*. Falls back to FTS5-only
        when the vector store is unavailable; returns [] when nothing is indexed."""
        allowed = set(source_ids)
        if not allowed or not self._fts_path.exists():
            return []
        # ADR-0057: same RRF fusion as the global hybrid retrieval, keyed by
        # this index's chunk_id (chunks have no path/offset fields).
        return rrf_fuse(
            [
                self._fts_search(query, allowed, limit=top_k * 3),
                self._vector_search(query, allowed, limit=top_k * 3),
            ],
            top_k=top_k,
            dedup_key=lambda chunk: str(chunk["chunk_id"]),
        )

    def _fts_search(self, query: str, allowed: set[str], limit: int) -> list[dict[str, Any]]:
        try:
            with sqlite3.connect(self._fts_path) as conn:
                conn.row_factory = sqlite3.Row
                # OR the terms: strict MATCH too easily returns nothing for
                # natural-language questions.
                terms = " OR ".join(f'"{word}"' for word in query.replace("?", " ").split() if word)
                if not terms:
                    return []
                rows = conn.execute(
                    "SELECT chunk_id, source_id, url, title, text FROM chunks WHERE chunks MATCH ?",
                    (terms,),
                ).fetchall()
            return [dict(row) for row in rows if row["source_id"] in allowed][:limit]
        except sqlite3.OperationalError:
            return []

    def _vector_search(self, query: str, allowed: set[str], limit: int) -> list[dict[str, Any]]:
        try:
            import chromadb

            client = chromadb.PersistentClient(path=str(self.index_dir / "chroma"))
            collection = client.get_or_create_collection("chat_index")
            vector = self.embedding_client.embed([query])[0]
            result = collection.query(query_embeddings=[vector], n_results=limit, include=["documents", "metadatas"])
            out: list[dict[str, Any]] = []
            for i, doc_id in enumerate(result["ids"][0]):
                meta = result["metadatas"][0][i] or {}
                if meta.get("source_id") not in allowed:
                    continue
                out.append(
                    {
                        "chunk_id": doc_id,
                        "source_id": meta.get("source_id", ""),
                        "url": meta.get("url", ""),
                        "title": meta.get("title", ""),
                        "text": result["documents"][0][i],
                    }
                )
            return out
        except Exception:
            logger.warning("Chat index vector search failed; falling back to FTS5", exc_info=True)
            return []
