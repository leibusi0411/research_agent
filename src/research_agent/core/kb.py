from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_agent.core.chroma_store import ChromaStore, _deterministic_embedding
from research_agent.core.config import load_user_config
from research_agent.core.ids import utc_now_iso
from research_agent.core.providers import EmbeddingClient
from research_agent.core.workspace import Workspace

logger = logging.getLogger(__name__)


SUPPORTED_SUFFIXES = {".md", ".txt", ".pdf", ".html", ".htm"}

# ADR-0049 chunking v2: target chunk size and overlap are decoupled from the
# old 3000/5000 pair — embedding models degrade on long mixed-topic chunks.
_CHUNK_SIZE = 1000
_CHUNK_OVERLAP = 100  # 10% of the window, so consecutive chunks share context.


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_path: str
    heading_path: list[str]
    start_offset: int
    end_offset: int
    text: str
    # ADR-0049: text enriched with the heading path / tags / wikilinks prefix.
    # FTS5 and the vector embedding index THIS field; ``text`` stays the clean
    # display form.  Empty for chunks created before enrichment.
    search_text: str = ""


@dataclass(frozen=True)
class ParsedFile:
    path: Path
    chunks: list[Chunk]
    metadata: dict[str, Any]


class KnowledgeBaseIndex:
    def __init__(
        self,
        workspace: Workspace,
        config_path: str | Path | None,
        *,
        fail_after_temp_build: bool = False,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self.workspace = workspace
        self.config_path = Path(config_path) if config_path is not None else None
        self.fail_after_temp_build = fail_after_temp_build
        self.embedding_client = embedding_client

    @property
    def index_dir(self) -> Path:
        return self.workspace.local_index_dir

    @property
    def manifest_path(self) -> Path:
        return self.index_dir / "manifest.json"

    @property
    def sqlite_path(self) -> Path:
        return self.index_dir / "fts.sqlite"

    @property
    def chroma_dir(self) -> Path:
        """ChromaDB directory — kept outside ``index_dir`` because HNSW
        segment files hold memory-mapped locks on Windows that prevent
        the atomic rename of the parent ``index_dir``."""
        return self.index_dir.parent / "chroma"

    @property
    def vector_path(self) -> Path:
        return self.chroma_dir / "chroma.sqlite3"

    def status(self) -> dict[str, Any]:
        config = load_user_config(self.config_path)
        vault_path = config.workspace.knowledge_base_path
        if (self.index_dir.parent / "local.building").exists():
            return _status("building", vault_path)
        failed_path = self.index_dir.parent / "local.failed.json"
        if failed_path.exists() and not self.manifest_path.exists():
            return _status("failed", vault_path)
        if not self.manifest_path.exists() or not self.sqlite_path.exists():
            return _status("missing", vault_path)
        if not self.vector_path.exists():
            return _status("failed", vault_path)

        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _status("failed", vault_path)

        current_files = _scan_files(vault_path)
        current_signature = _file_signature(current_files)
        manifest_signature = {
            file_record["path"]: {
                "mtime": file_record["mtime"],
                "size": file_record["size"],
            }
            for file_record in manifest.get("files", [])
        }
        status = "ready" if current_signature == manifest_signature else "stale"
        return {
            "status": status,
            "vault_path": str(vault_path),
            "file_count": int(manifest.get("file_count", 0)),
            "chunk_count": int(manifest.get("chunk_count", 0)),
            "last_indexed_at": manifest.get("built_at"),
        }

    def update(self, *, max_files: int | None = None) -> dict[str, Any]:
        """Incrementally refresh the index for new/changed/deleted vault files.

        In-place update of the existing FTS5 index and Chroma collection —
        unlike :meth:`rebuild`, unchanged files keep their chunks and are not
        re-embedded.  Vault files are never touched (read-only ingestion,
        ADR-0006).

        When the number of pending changes exceeds *max_files* the update is
        skipped (``skipped: True``, status stays ``stale``) so callers can
        degrade gracefully instead of paying a surprise bulk re-embedding.
        """
        config = load_user_config(self.config_path)
        vault_path = config.workspace.knowledge_base_path
        if not self.manifest_path.exists() or not self.sqlite_path.exists():
            return {
                **self.status(),
                "updated_files": 0,
                "skipped": True,
                "reason": "index_missing",
            }

        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest_records = {
            record["path"]: record for record in manifest.get("files", [])
        }
        current_files = _scan_files(vault_path)
        current_paths = {str(path) for path in current_files}
        changed_files = [
            path
            for path in current_files
            if str(path) not in manifest_records
            or _record_differs(manifest_records[str(path)], path)
        ]
        deleted_paths = sorted(set(manifest_records) - current_paths)
        if not changed_files and not deleted_paths:
            return {**self.status(), "updated_files": 0, "skipped": False}
        if max_files is not None and len(changed_files) + len(deleted_paths) > max_files:
            return {
                **self.status(),
                "updated_files": 0,
                "skipped": True,
                "reason": "too_many_changes",
                "pending_files": len(changed_files) + len(deleted_paths),
            }

        marker = self.index_dir.parent / "local.building"
        self.index_dir.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("building", encoding="utf-8")
        chroma_error: str | None = None
        try:
            parsed_changed = [_parse_file(path) for path in changed_files]
            new_chunks = [chunk for parsed in parsed_changed for chunk in parsed.chunks]
            affected_paths = [str(path) for path in changed_files] + deleted_paths

            removed_chunk_ids: list[str] = []
            connection = sqlite3.connect(self.sqlite_path)
            try:
                placeholders = ",".join("?" for _ in affected_paths)
                removed_chunk_ids = [
                    row[0]
                    for row in connection.execute(
                        f"SELECT chunk_id FROM chunks WHERE source_path IN ({placeholders})",
                        affected_paths,
                    ).fetchall()
                ]
                if removed_chunk_ids:
                    id_placeholders = ",".join("?" for _ in removed_chunk_ids)
                    connection.execute(
                        f"DELETE FROM chunks_fts WHERE chunk_id IN ({id_placeholders})",
                        removed_chunk_ids,
                    )
                if affected_paths:
                    connection.execute(
                        f"DELETE FROM chunks WHERE source_path IN ({placeholders})",
                        affected_paths,
                    )
                for chunk in new_chunks:
                    heading_path = json.dumps(chunk.heading_path, ensure_ascii=False)
                    connection.execute(
                        """
                        INSERT INTO chunks (
                          chunk_id, source_path, heading_path, start_offset, end_offset, text
                        )
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chunk.chunk_id,
                            chunk.source_path,
                            heading_path,
                            chunk.start_offset,
                            chunk.end_offset,
                            chunk.text,
                        ),
                    )
                    connection.execute(
                        "INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)",
                        (chunk.chunk_id, chunk.search_text or chunk.text),
                    )
                connection.commit()
            finally:
                connection.close()

            try:
                store = ChromaStore(self.chroma_dir)
                try:
                    store.delete_ids(removed_chunk_ids)
                    store.add_chunks(new_chunks, self.embedding_client)
                finally:
                    # Windows: HNSW segment mmaps block later atomic swaps.
                    store.close()
            except Exception as exc:
                chroma_error = str(exc)
                logger.warning(
                    "Chroma incremental update failed; FTS5 is up to date: %s", exc
                )

            self._refresh_manifest(
                manifest,
                parsed_changed,
                deleted_paths,
                removed_chunk_count=len(removed_chunk_ids),
                added_chunk_count=len(new_chunks),
                vault_path=vault_path,
            )
        finally:
            marker.unlink(missing_ok=True)

        result = {
            **self.status(),
            "updated_files": len(changed_files),
            "deleted_files": len(deleted_paths),
        }
        if chroma_error is not None:
            result["status"] = "stale"
            result["error"] = chroma_error
        return result

    def _refresh_manifest(
        self,
        manifest: dict[str, Any],
        parsed_changed: list[ParsedFile],
        deleted_paths: list[str],
        *,
        removed_chunk_count: int,
        added_chunk_count: int,
        vault_path: Path,
    ) -> None:
        records = {record["path"]: record for record in manifest.get("files", [])}
        for path_str in deleted_paths:
            records.pop(path_str, None)
        for parsed in parsed_changed:
            stat = parsed.path.stat()
            records[str(parsed.path)] = {
                "path": str(parsed.path),
                "mtime": int(stat.st_mtime_ns),
                "size": stat.st_size,
                **parsed.metadata,
            }
        updated_manifest = {
            "status": "ready",
            "vault_path": str(vault_path),
            "built_at": utc_now_iso(datetime.now(timezone.utc)),
            "file_count": len(records),
            "chunk_count": int(manifest.get("chunk_count", 0)) - removed_chunk_count + added_chunk_count,
            "files": sorted(records.values(), key=lambda record: record["path"]),
        }
        tmp_manifest = self.manifest_path.with_suffix(".json.tmp")
        tmp_manifest.write_text(
            json.dumps(updated_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_manifest, self.manifest_path)

    def rebuild(self) -> dict[str, Any]:
        config = load_user_config(self.config_path)
        vault_path = config.workspace.knowledge_base_path
        self.workspace.ensure()
        files = _scan_files(vault_path)
        parsed_files: list[ParsedFile] = []
        for file_path in files:
            parsed_files.append(_parse_file(file_path))
        chunks = [chunk for parsed_file in parsed_files for chunk in parsed_file.chunks]

        tmp_parent = self.index_dir.parent
        tmp_parent.mkdir(parents=True, exist_ok=True)
        building_marker = tmp_parent / "local.building"
        failed_marker = tmp_parent / "local.failed.json"
        building_marker.write_text("building", encoding="utf-8")
        tmp_dir = Path(tempfile.mkdtemp(prefix="local-build-", dir=tmp_parent))

        try:
            # Step 1: Build FTS5 + manifest in temp dir
            _write_sqlite_index(tmp_dir / "fts.sqlite", chunks)
            manifest = _build_manifest(vault_path, parsed_files, chunks)
            (tmp_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if self.fail_after_temp_build:
                raise RuntimeError("simulated rebuild failure")

            # Atomically deploy FTS5 index (always, even if Chroma fails later)
            _atomic_swap_fts5(tmp_dir, self.index_dir)

            # Step 2: Build ChromaDB separately — failure here does NOT roll
            # back the FTS5 index, so keyword search still works.
            chroma_error: str | None = None
            chroma_tmp: Path | None = None
            try:
                chroma_tmp = Path(
                    tempfile.mkdtemp(prefix="chroma-build-", dir=tmp_parent)
                )
                _write_chroma_index(chroma_tmp, chunks, self.embedding_client)
                self.chroma_dir.mkdir(parents=True, exist_ok=True)
                shutil.copytree(chroma_tmp, self.chroma_dir, dirs_exist_ok=True)
            except Exception as chroma_exc:
                chroma_error = str(chroma_exc)
                logger.warning(
                    "ChromaDB index build failed; FTS5 is still available: %s",
                    chroma_exc,
                )
            finally:
                if chroma_tmp is not None and chroma_tmp.exists():
                    shutil.rmtree(chroma_tmp, ignore_errors=True)

            building_marker.unlink(missing_ok=True)
            failed_marker.unlink(missing_ok=True)

            result: dict[str, Any] = {
                "status": "ready" if chroma_error is None else "stale",
                "vault_path": str(vault_path),
                "file_count": len(files),
                "chunk_count": len(chunks),
                "last_indexed_at": manifest["built_at"],
            }
            if chroma_error:
                result["error"] = chroma_error
            return result
        except Exception as exc:  # noqa: BLE001 - FTS5 build failure → roll back
            building_marker.unlink(missing_ok=True)
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            failed_marker.write_text(
                json.dumps({"error": str(exc), "failed_at": utc_now_iso()}, ensure_ascii=False),
                encoding="utf-8",
            )
            current_status = self.status()
            if current_status["status"] in {"ready", "stale"}:
                return {**current_status, "status": "stale", "error": str(exc)}
            return {**_status("failed", vault_path), "error": str(exc)}


def _atomic_swap_fts5(tmp_dir: Path, index_dir: Path) -> None:
    """Atomically swap the new FTS5+manifest directory in, removing the old one."""
    backup_dir = index_dir.with_name("local.backup")
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    if index_dir.exists():
        os.rename(index_dir, backup_dir)
    try:
        os.rename(tmp_dir, index_dir)
    except Exception:
        if backup_dir.exists() and not index_dir.exists():
            os.rename(backup_dir, index_dir)
        raise
    if backup_dir.exists():
        shutil.rmtree(backup_dir)


def _status(status: str, vault_path: Path) -> dict[str, Any]:
    return {
        "status": status,
        "vault_path": str(vault_path),
        "file_count": 0,
        "chunk_count": 0,
        "last_indexed_at": None,
    }


def _scan_files(vault_path: Path) -> list[Path]:
    return sorted(
        path
        for path in vault_path.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )


def _file_signature(files: list[Path]) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for path in files:
        stat = path.stat()
        result[str(path)] = {"mtime": int(stat.st_mtime_ns), "size": stat.st_size}
    return result


def _record_differs(record: dict[str, Any], path: Path) -> bool:
    stat = path.stat()
    return record.get("mtime") != int(stat.st_mtime_ns) or record.get("size") != stat.st_size


def _build_manifest(vault_path: Path, parsed_files: list[ParsedFile], chunks: list[Chunk]) -> dict[str, Any]:
    files = []
    for parsed in parsed_files:
        stat = parsed.path.stat()
        files.append({
            "path": str(parsed.path),
            "mtime": int(stat.st_mtime_ns),
            "size": stat.st_size,
            **parsed.metadata,
        })
    return {
        "status": "ready",
        "vault_path": str(vault_path),
        "built_at": utc_now_iso(datetime.now(timezone.utc)),
        "file_count": len(parsed_files),
        "chunk_count": len(chunks),
        "files": files,
    }


def _parse_file(path: Path) -> ParsedFile:
    suffix = path.suffix.lower()
    if suffix == ".md":
        chunks, metadata = _chunk_markdown(path)
        return ParsedFile(path=path, chunks=chunks, metadata=metadata)
    text = _extract_text(path)
    chunks = _paragraph_chunks(path, text, [])
    return ParsedFile(path=path, chunks=chunks, metadata={"title": path.stem, "headings": [], "links": [], "wikilinks": [], "frontmatter": {}})


def _chunk_markdown(path: Path) -> tuple[list[Chunk], dict[str, Any]]:
    raw = path.read_text(encoding="utf-8-sig")
    content_start = 0
    frontmatter: dict[str, Any] = {}
    if raw.startswith("---"):
        end = raw.find("\n---", 3)
        if end != -1:
            frontmatter = _parse_frontmatter(raw[3:end])
            content_start = raw.find("\n", end + 4) + 1
    content = raw[content_start:]
    # ADR-0049: tags 和 wikilinks 是用户刻意打上的检索信号，与标题路径一起
    # 前置进 search_text，供 FTS5 / 向量两路匹配（manifest 仍保留原始记录）。
    tags = _normalize_tags(frontmatter.get("tags"))
    wikilinks = re.findall(r"\[\[([^\]]+)\]\]", content)
    chunks: list[Chunk] = []
    current_headings: list[str] = []
    headings: list[str] = []
    section_start = content_start
    section_lines: list[str] = []
    offset = content_start

    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("#"):
            if section_lines:
                chunks.extend(_paragraph_chunks(path, "".join(section_lines), current_headings, section_start, tags, wikilinks))
            level = len(stripped) - len(stripped.lstrip("#"))
            heading = stripped[level:].strip()
            headings.append(heading)
            current_headings = current_headings[: level - 1] + [heading]
            section_lines = []
            section_start = offset + len(line)
        else:
            section_lines.append(line)
        offset += len(line)

    if section_lines:
        chunks.extend(_paragraph_chunks(path, "".join(section_lines), current_headings, section_start, tags, wikilinks))
    metadata = {
        "frontmatter": frontmatter,
        "title": frontmatter.get("title") or (headings[0] if headings else path.stem),
        "headings": headings,
        "links": re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", content),
        "wikilinks": wikilinks,
    }
    return chunks, metadata


def _normalize_tags(value: Any) -> list[str]:
    """Normalize frontmatter tags (YAML list or inline string) into tokens."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in re.split(r"[,，\s]+", str(value)) if part.strip()]


def _compose_search_text(
    text: str,
    heading_path: list[str],
    tags: list[str],
    wikilinks: list[str],
) -> str:
    """Prefix display text with heading path / tags / wikilinks for indexing.

    FTS5 matches the tokens in the prefix and the vector embedding absorbs the
    heading signal, while ``text`` stays the clean display form (ADR-0049).
    """
    parts: list[str] = []
    if heading_path:
        parts.append("[" + " > ".join(heading_path) + "]")
    if tags:
        parts.append(" ".join(f"#{tag}" for tag in tags))
    if wikilinks:
        parts.append(" ".join(f"[[{w}]]" for w in wikilinks))
    prefix = " ".join(parts)
    return f"{prefix}\n{text}" if prefix else text


def _make_chunk(
    path: Path,
    text: str,
    heading_path: list[str],
    start_offset: int,
    end_offset: int,
    tags: list[str],
    wikilinks: list[str],
) -> Chunk:
    return Chunk(
        chunk_id=_chunk_id(path, start_offset, end_offset),
        source_path=str(path),
        heading_path=heading_path,
        start_offset=start_offset,
        end_offset=end_offset,
        text=text,
        search_text=_compose_search_text(text, heading_path, tags, wikilinks),
    )


def _parse_frontmatter(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if value.startswith("[") and value.endswith("]"):
            data[key.strip()] = [item.strip() for item in value[1:-1].split(",") if item.strip()]
        else:
            data[key.strip()] = value.strip("\"'")
    return data


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return path.read_text(encoding="utf-8-sig", errors="ignore")
    if suffix in {".html", ".htm"}:
        raw = path.read_text(encoding="utf-8-sig", errors="ignore")
        try:
            import trafilatura

            return trafilatura.extract(raw) or ""
        except Exception as exc:
            logger.warning("HTML extraction via trafilatura failed for %s: %s — falling back to regex strip", path, exc)
            return re.sub(r"<[^>]+>", " ", raw)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            logger.warning("PDF extraction failed for %s: %s", path, exc)
            return ""
    logger.warning("Unsupported file type for extraction: %s (suffix: %s)", path, suffix)
    return ""


def _flush_pending(
    pending: list[tuple[str, int, int]],
    carry: str,
    chunks: list[Chunk],
    path: Path,
    heading_path: list[str],
    tags: list[str],
    wikilinks: list[str],
) -> str:
    """Flush accumulated paragraphs into one chunk; return its text as the
    overlap carry for the next chunk (ADR-0049)."""
    if not pending:
        return carry
    body = "\n\n".join(item[0] for item in pending)
    chunk_text = (carry + "\n\n" if carry else "") + body
    chunks.append(
        _make_chunk(path, chunk_text, heading_path, pending[0][1], pending[-1][2], tags, wikilinks)
    )
    pending.clear()
    return chunk_text


def _split_long_paragraph(
    paragraph: str,
    start_offset: int,
    path: Path,
    heading_path: list[str],
    chunks: list[Chunk],
    tags: list[str],
    wikilinks: list[str],
) -> None:
    """Split an oversized paragraph into sliding windows with 10% overlap.

    Consecutive windows share ``_CHUNK_OVERLAP`` characters so concepts that
    straddle a window boundary keep context on both sides (ADR-0049).
    """
    stride = _CHUNK_SIZE - _CHUNK_OVERLAP
    index = 0
    while index < len(paragraph):
        part = paragraph[index : index + _CHUNK_SIZE]
        part_start = start_offset + index
        chunks.append(
            _make_chunk(path, part, heading_path, part_start, part_start + len(part), tags, wikilinks)
        )
        if index + _CHUNK_SIZE >= len(paragraph):
            break
        index += stride


def _paragraph_chunks(
    path: Path,
    text: str,
    heading_path: list[str],
    base_offset: int = 0,
    tags: list[str] | None = None,
    wikilinks: list[str] | None = None,
) -> list[Chunk]:
    tags = tags or []
    wikilinks = wikilinks or []
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks: list[Chunk] = []
    cursor = 0
    pending: list[tuple[str, int, int]] = []
    carry = ""

    for paragraph in paragraphs:
        relative_start = text.find(paragraph, cursor)
        start_offset = base_offset + max(relative_start, 0)
        end_offset = start_offset + len(paragraph)
        cursor = relative_start + len(paragraph)

        if len(paragraph) > _CHUNK_SIZE:
            carry = _flush_pending(pending, carry, chunks, path, heading_path, tags, wikilinks)
            _split_long_paragraph(paragraph, start_offset, path, heading_path, chunks, tags, wikilinks)
            # Sliding windows already overlap each other; no carry across.
            carry = ""
            continue

        pending_len = sum(len(item[0]) for item in pending) + max(0, len(pending) - 1) * 2
        if carry:
            pending_len += len(carry) + 2
        if pending and pending_len + len(paragraph) + 2 > _CHUNK_SIZE:
            carry = _flush_pending(pending, carry, chunks, path, heading_path, tags, wikilinks)[-_CHUNK_OVERLAP:]
        pending.append((paragraph, start_offset, end_offset))
    _flush_pending(pending, carry, chunks, path, heading_path, tags, wikilinks)
    return chunks


def _write_chroma_index(path: Path, chunks: list[Chunk], embedding_client: EmbeddingClient | None = None) -> None:
    store = ChromaStore(path)
    store.build_index(chunks, embedding_client)
    store.close()  # release SQLite handles; segment files stay mmap'd on Windows


def _chunk_id(path: Path, start_offset: int, end_offset: int) -> str:
    stat = path.stat()
    digest = hashlib.sha1(
        f"{path}|{start_offset}|{end_offset}|{stat.st_mtime_ns}|{stat.st_size}".encode("utf-8")
    ).hexdigest()[:12]
    return f"chunk_{digest}"


def _write_sqlite_index(path: Path, chunks: list[Chunk]) -> None:
    connection = sqlite3.connect(path)
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            CREATE TABLE chunks (
              chunk_id TEXT PRIMARY KEY,
              source_path TEXT NOT NULL,
              heading_path TEXT NOT NULL,
              start_offset INTEGER NOT NULL,
              end_offset INTEGER NOT NULL,
              text TEXT NOT NULL
            )
            """
        )
        cursor.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5(chunk_id, text)")
        for chunk in chunks:
            heading_path = json.dumps(chunk.heading_path, ensure_ascii=False)
            cursor.execute(
                """
                INSERT INTO chunks (
                  chunk_id, source_path, heading_path, start_offset, end_offset, text
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk.chunk_id,
                    chunk.source_path,
                    heading_path,
                    chunk.start_offset,
                    chunk.end_offset,
                    chunk.text,
                ),
            )
            cursor.execute(
                "INSERT INTO chunks_fts (chunk_id, text) VALUES (?, ?)",
                (chunk.chunk_id, chunk.search_text or chunk.text),
            )
        connection.commit()
    finally:
        cursor.close()
        connection.close()
