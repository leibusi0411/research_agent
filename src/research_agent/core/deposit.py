"""Knowledge Deposit: explicitly save a finished Web Report File into the Markdown Vault.

Deposit is additive-only: it writes one new note per task under
``<vault>/web-research/`` and never modifies, moves, or deletes existing
vault notes (see ADR-0006 for the read-only ingestion boundary and
ADR-0045 for the deposit decision).
"""
from __future__ import annotations

import os
from pathlib import Path

from research_agent.core.config import load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.tasks import TaskStore
from research_agent.core.workspace import Workspace

DEPOSIT_DIR_NAME = "web-research"


def deposit_web_report(
    *,
    task_id: str,
    workspace: Workspace,
    task_store: TaskStore,
    config_path: Path | None,
) -> dict[str, str]:
    """Copy the completed Web Report File of *task_id* into the Markdown Vault.

    Returns ``{"task_id": ..., "vault_path": ...}`` with the deposited note path.
    Raises ``ResearchError`` with codes ``task_not_found``, ``invalid_task_mode``,
    ``report_missing``, ``already_deposited``, ``config_missing``,
    ``config_invalid`` or ``file_write_error``.
    """
    record = task_store.get_finished_task(task_id)
    if record is None:
        raise ResearchError(code="task_not_found", message="Task not found.")
    if record.mode != "web":
        raise ResearchError(
            code="invalid_task_mode",
            message=f"Only Web Research tasks can be deposited (task mode: {record.mode}).",
        )
    report_path = _resolve_report_path(workspace, record.report_path)
    if record.status != "completed" or report_path is None or not report_path.exists():
        raise ResearchError(
            code="report_missing",
            message="Task has no completed Web Report File to deposit.",
        )

    config = load_user_config(config_path)
    vault_path = config.workspace.knowledge_base_path
    if not vault_path.is_dir():
        raise ResearchError(
            code="config_invalid",
            message=f"Knowledge Base path does not exist: {vault_path}",
        )
    deposit_dir = vault_path / DEPOSIT_DIR_NAME
    if _already_deposited(deposit_dir, task_id):
        raise ResearchError(
            code="already_deposited",
            message="This task's report is already deposited in the Knowledge Base.",
        )

    try:
        content = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ResearchError(
            code="file_write_error",
            message=f"Failed to read Web Report File: {exc}",
        ) from exc

    try:
        deposit_dir.mkdir(parents=True, exist_ok=True)
        target = _claim_deposit_path(deposit_dir, report_path.name)
    except OSError as exc:
        raise ResearchError(
            code="file_write_error",
            message=f"Failed to deposit report into Knowledge Base: {exc}",
        ) from exc

    # The name is claimed (an empty placeholder file sits at ``target``). Write
    # the real content via a task-unique temp file + rename so a crash never
    # leaves a half-written note, and clean up both files on failure.
    temp_path = target.with_name(f"{target.name}.{task_id}.tmp")
    try:
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(target)
    except OSError as exc:
        temp_path.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise ResearchError(
            code="file_write_error",
            message=f"Failed to deposit report into Knowledge Base: {exc}",
        ) from exc
    return {"task_id": task_id, "vault_path": str(target)}


def _resolve_report_path(workspace: Workspace, report_path: str | None) -> Path | None:
    # No workspace-containment check (unlike _delete_report_file): the path comes
    # from our own tasks.sqlite record, and only its basename is used for the
    # vault write — the deposited file always lands inside <vault>/web-research/.
    if not report_path:
        return None
    path = Path(report_path)
    if not path.is_absolute():
        path = workspace.root / path
    return path


def _already_deposited(deposit_dir: Path, task_id: str) -> bool:
    """A task counts as deposited when a deposit-dir note carries its task_id in frontmatter.

    Depends on the exact ``task_id: "..."`` frontmatter line written by
    ``report.py::render_web_report`` — keep the two in sync. Only the
    frontmatter block is scanned so a task_id mentioned in a note's body
    does not block a legitimate deposit.
    """
    if not deposit_dir.is_dir():
        return False
    marker = f'task_id: "{task_id}"'
    for note in deposit_dir.glob("*.md"):
        try:
            frontmatter = _frontmatter_block(note.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            # Unreadable or non-UTF-8 notes are skipped: worst case a duplicate
            # is deposited, which is safer than crashing the whole operation.
            continue
        if marker in frontmatter:
            return True
    return False


def _frontmatter_block(text: str) -> str:
    """Return the content between the first two ``---`` lines, or "" when absent."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[1:index])
    return ""


def _claim_deposit_path(deposit_dir: Path, filename: str) -> Path:
    """Atomically reserve a deposit filename, appending -2/-3... on collision.

    Uses ``O_CREAT | O_EXCL`` so concurrent deposits can never claim the same
    name (removes the check-then-write race). The reserved placeholder file is
    overwritten by the caller via temp-file rename, or unlinked on failure.
    """
    stem = Path(filename).stem
    suffix = Path(filename).suffix or ".md"
    candidate = deposit_dir / filename
    counter = 2
    while True:
        try:
            fd = os.open(str(candidate), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            candidate = deposit_dir / f"{stem}-{counter}{suffix}"
            counter += 1
            continue
        os.close(fd)
        return candidate
