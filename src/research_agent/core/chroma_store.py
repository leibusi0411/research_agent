from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import chromadb

from research_agent.core.providers import EmbeddingClient


class ChromaStore:
    """ChromaDB-backed vector index for Local RAG chunks.

    Replaces the previous SQLite JSON-embedding table with a real
    persistent ChromaDB collection, fulfilling ADR-0026's original
    intent of using Chroma for vector search alongside SQLite FTS5.
    """

    COLLECTION_NAME = "local_rag_chunks"

    def __init__(self, persist_path: str | Path) -> None:
        self._persist_path = Path(persist_path)
        self._client: chromadb.Client = chromadb.PersistentClient(
            path=str(self._persist_path)
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release all client resources including HNSW segment files.

        Calls ``PersistentClient.close()`` which shuts down the internal
        server, closes SQLite connections, and releases memory-mapped
        segment files so the persist directory can be moved or deleted
        on all platforms.
        """
        if self._client is None:
            return
        # R-115: ``_closed`` is a ChromaDB internal attribute with no public
        # API alternative.  Accessing it is the least-bad way to avoid a
        # duplicate-close error when ``close()`` is called multiple times.
        try:
            already_closed = self._client._closed
        except AttributeError:
            already_closed = False
        if not already_closed:
            self._client.close()
        self._client = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Index build
    # ------------------------------------------------------------------

    def build_index(
        self,
        chunks: list[Any],
        embedding_client: EmbeddingClient | None,
    ) -> None:
        """Rebuild the Chroma collection from scratch.

        If the store has been closed, the client is transparently re-opened
        so that repeated build → close → build cycles work without forcing
        the caller to create a new instance (fixes R-62).
        """
        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self._persist_path))

        try:
            self._client.delete_collection(name=self.COLLECTION_NAME)
        except (ValueError, chromadb.errors.NotFoundError):
            pass  # Collection does not exist yet — safe to proceed

        if not chunks:
            self._client.get_or_create_collection(name=self.COLLECTION_NAME)
            return

        self.add_chunks(chunks, embedding_client)

    def add_chunks(
        self,
        chunks: list[Any],
        embedding_client: EmbeddingClient | None,
    ) -> None:
        """Append chunks to the collection (incremental update support).

        Embeds in batches to stay within API limits (e.g. token count per
        request).  Default batch size of 32 is conservative for most
        providers; larger values risk 400 errors on long chunks.  Without an
        embedding client, deterministic pseudo-embeddings are used (offline
        tests).
        """
        if not chunks:
            return
        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self._persist_path))

        _EMBED_BATCH_SIZE = 32
        if embedding_client is not None:
            embeddings: list[list[float]] = []
            for i in range(0, len(chunks), _EMBED_BATCH_SIZE):
                batch = chunks[i : i + _EMBED_BATCH_SIZE]
                embeddings.extend(embedding_client.embed([c.text for c in batch]))
        else:
            embeddings = [_deterministic_embedding(c.text) for c in chunks]

        self._client.get_or_create_collection(name=self.COLLECTION_NAME).add(
            ids=[chunk.chunk_id for chunk in chunks],
            embeddings=embeddings,
            documents=[chunk.text for chunk in chunks],
            metadatas=[
                {
                    "source_path": chunk.source_path,
                    "heading_path": json.dumps(
                        chunk.heading_path, ensure_ascii=False
                    ),
                    "start_offset": chunk.start_offset,
                    "end_offset": chunk.end_offset,
                }
                for chunk in chunks
            ],
        )

    def delete_ids(self, ids: list[str]) -> None:
        """Remove chunks by id (incremental update support)."""
        if not ids:
            return
        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self._persist_path))
        try:
            collection = self._client.get_collection(name=self.COLLECTION_NAME)
        except Exception:
            return  # Collection does not exist — nothing to delete
        collection.delete(ids=ids)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def query(
        self, query_embedding: list[float], n_results: int = 10
    ) -> list[dict[str, Any]]:
        """Semantic search: return nearest-neighbour chunks by cosine distance."""
        if self._client is None:
            self._client = chromadb.PersistentClient(path=str(self._persist_path))
        try:
            collection = self._client.get_collection(name=self.COLLECTION_NAME)
        except Exception:
            return []

        if collection.count() == 0:
            return []

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
        )

        ids_batch = results.get("ids")
        if not ids_batch or not ids_batch[0]:
            return []

        items: list[dict[str, Any]] = []
        for idx, chunk_id in enumerate(ids_batch[0]):
            # Defensive access: ChromaDB may omit metadata/documents/distances
            # for some results.  Build safe defaults per index.
            try:
                meta = _safe_nth(results.get("metadatas"), idx, {}) or {}
                doc = _safe_nth(results.get("documents"), idx, "")
                distance = _safe_nth(results.get("distances"), idx, 0.0)
                items.append(
                    {
                        "chunk_id": chunk_id,
                        "text": doc or "",
                        "source_path": str(meta.get("source_path", "")),
                        "heading_path": json.loads(meta.get("heading_path", "[]")),
                        "start_offset": int(meta.get("start_offset", 0)),
                        "end_offset": int(meta.get("end_offset", 0)),
                        "score": float(distance),
                    }
                )
            except (json.JSONDecodeError, TypeError, AttributeError, ValueError):
                continue
        return items

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def count(self) -> int:
        if self._client is None:
            return 0
        try:
            return self._client.get_collection(name=self.COLLECTION_NAME).count()
        except Exception:
            return 0


def _safe_nth(batch: list[list[Any]] | None, idx: int, default: Any) -> Any:
    """Return ``batch[0][idx]`` safely, or *default* if missing/None."""
    if not batch or not batch[0] or idx >= len(batch[0]):
        return default
    val = batch[0][idx]
    return default if val is None else val


def _deterministic_embedding(text: str) -> list[float]:
    """Deterministic pseudo-embedding for offline tests (no real model)."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [
        int.from_bytes(digest[i : i + 4], "big") / 2**32 for i in range(0, 32, 4)
    ]
