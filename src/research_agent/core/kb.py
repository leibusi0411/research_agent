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


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_path: str
    heading_path: list[str]
    start_offset: int
    end_offset: int
    text: str


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
        chroma_tmp: Path | None = Path(
            tempfile.mkdtemp(prefix="chroma-build-", dir=tmp_parent)
        )
        try:
            # 1. Build FTS5 + manifest in temp dir
            _write_sqlite_index(tmp_dir / "fts.sqlite", chunks)
            manifest = _build_manifest(vault_path, parsed_files, chunks)
            (tmp_dir / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if self.fail_after_temp_build:
                raise RuntimeError("simulated rebuild failure")

            # Build ChromaDB in its own temp directory (outside index_dir).
            # ChromaDB's HNSW segment files hold memory-mapped locks on
            # Windows that prevent renaming/deleting the directory within
            # the same process.  Building in a fresh temp dir and then
            # copying over the old one works because file reads are
            # allowed even when the target files are locked.
            _write_chroma_index(chroma_tmp, chunks, self.embedding_client)

            # 2. Atomic swap: move old FTS5+manifest aside, bring new in
            backup_dir = self.index_dir.with_name("local.backup")
            if backup_dir.exists():
                shutil.rmtree(backup_dir)
            if self.index_dir.exists():
                os.rename(self.index_dir, backup_dir)
            try:
                os.rename(tmp_dir, self.index_dir)
            except Exception:
                if backup_dir.exists() and not self.index_dir.exists():
                    os.rename(backup_dir, self.index_dir)
                raise
            if backup_dir.exists():
                shutil.rmtree(backup_dir)

            # 3. Copy new ChromaDB over the old one
            self.chroma_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(chroma_tmp, self.chroma_dir, dirs_exist_ok=True)

            building_marker.unlink(missing_ok=True)
            failed_marker.unlink(missing_ok=True)
            return {
                "status": "ready",
                "vault_path": str(vault_path),
                "file_count": len(files),
                "chunk_count": len(chunks),
                "last_indexed_at": manifest["built_at"],
            }
        except Exception as exc:  # noqa: BLE001 - normalized into status result
            building_marker.unlink(missing_ok=True)
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
            # Clean up only the temp chroma build; keep the prior chroma_dir
            # intact so the previous vector index is preserved.
            if chroma_tmp is not None and chroma_tmp.exists():
                shutil.rmtree(chroma_tmp, ignore_errors=True)
            failed_marker.write_text(
                json.dumps({"error": str(exc), "failed_at": utc_now_iso()}, ensure_ascii=False),
                encoding="utf-8",
            )
            current_status = self.status()
            if current_status["status"] in {"ready", "stale"}:
                return {**current_status, "status": "stale", "error": str(exc)}
            return {**_status("failed", vault_path), "error": str(exc)}


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
                chunks.extend(_paragraph_chunks(path, "".join(section_lines), current_headings, section_start))
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
        chunks.extend(_paragraph_chunks(path, "".join(section_lines), current_headings, section_start))
    metadata = {
        "frontmatter": frontmatter,
        "title": frontmatter.get("title") or (headings[0] if headings else path.stem),
        "headings": headings,
        "links": re.findall(r"(?<!!)\[[^\]]+\]\(([^)]+)\)", content),
        "wikilinks": re.findall(r"\[\[([^\]]+)\]\]", content),
    }
    return chunks, metadata


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
        except Exception:
            return re.sub(r"<[^>]+>", " ", raw)
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader  # type: ignore

            reader = PdfReader(str(path))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            logger.warning("PDF extraction failed for %s: %s", path, exc)
            return ""
    return ""


def _paragraph_chunks(
    path: Path,
    text: str,
    heading_path: list[str],
    base_offset: int = 0,
) -> list[Chunk]:
    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    chunks: list[Chunk] = []
    cursor = 0
    pending: list[tuple[str, int, int]] = []

    def flush_pending() -> None:
        if not pending:
            return
        chunk_text = "\n\n".join(item[0] for item in pending)
        chunks.append(
            Chunk(
                chunk_id=_chunk_id(path, pending[0][1], pending[-1][2]),
                source_path=str(path),
                heading_path=heading_path,
                start_offset=pending[0][1],
                end_offset=pending[-1][2],
                text=chunk_text,
            )
        )
        pending.clear()

    for paragraph in paragraphs:
        relative_start = text.find(paragraph, cursor)
        start_offset = base_offset + max(relative_start, 0)
        end_offset = start_offset + len(paragraph)
        cursor = relative_start + len(paragraph)
        if len(paragraph) > 5000:
            flush_pending()
            for index in range(0, len(paragraph), 5000):
                part = paragraph[index : index + 5000]
                part_start = start_offset + index
                chunks.append(
                    Chunk(
                        chunk_id=_chunk_id(path, part_start, part_start + len(part)),
                        source_path=str(path),
                        heading_path=heading_path,
                        start_offset=part_start,
                        end_offset=part_start + len(part),
                        text=part,
                    )
                )
            continue
        pending_text_len = sum(len(item[0]) for item in pending) + max(0, len(pending) - 1) * 2
        if pending and pending_text_len + len(paragraph) + 2 > 3000:
            flush_pending()
        pending.append((paragraph, start_offset, end_offset))
        if sum(len(item[0]) for item in pending) >= 3000:
            flush_pending()
    flush_pending()
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
                (chunk.chunk_id, chunk.text),
            )
        connection.commit()
    finally:
        cursor.close()
        connection.close()
