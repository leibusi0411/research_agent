"""Grounded chat over a finished research task (ADR-0050).

A deliberately thin, single-role Q&A service — no LangGraph, no tools.
Context is two layers:

* static grounding — the task's own ``result.json`` (question, curator
  summary, findings, sources), optionally narrowed to the source ids the
  user selected in the UI;
* rolling history — ``chat.jsonl`` inside the task folder, appended one
  user/assistant pair per turn and replayed into each prompt.

The chat model client is the same ``complete()`` interface the rest of
the system already uses (``ChatModelClient`` protocol).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from research_agent.core.errors import ResearchError
from research_agent.core.ids import utc_now_iso
from research_agent.core.providers import ChatModelClient

logger = logging.getLogger(__name__)

_HISTORY_FILE = "chat.jsonl"

_SYSTEM_PROMPT = (
    "You are a research assistant answering questions about a completed research task. "
    "Answer ONLY from the research context below (question, summary, findings, sources). "
    "When you rely on a source, cite it by its [S1]-style number. "
    "If the research context does not answer the question, say so plainly instead of guessing."
)

# Hard caps so a huge report cannot blow the chat context window. Findings
# and report sections are each capped separately (additive in the worst
# case); findings drop oldest-subtask-first beyond their budget.
_MAX_CONTEXT_CHARS = 24_000
# R-283: the References card imports sources explicitly (NotebookLM-style);
# 50 is the per-conversation import ceiling, enforced front and back.
_MAX_IMPORTED_SOURCES = 50


class TaskChatService:
    """Answer follow-up questions against one finished task's artifacts."""

    def __init__(self, *, task_dir: Path, chat_model: ChatModelClient | None) -> None:
        self.task_dir = Path(task_dir)
        self.chat_model = chat_model

    # ── history ─────────────────────────────────────────────────────────

    @property
    def _history_path(self) -> Path:
        return self.task_dir / _HISTORY_FILE

    def history(self) -> list[dict[str, Any]]:
        """Replay the persisted conversation (empty list for a fresh task)."""
        if not self._history_path.exists():
            return []
        messages: list[dict[str, Any]] = []
        for line in self._history_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                messages.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("skipping malformed chat history line in %s", self._history_path)
        return messages

    # ── send ────────────────────────────────────────────────────────────

    def send(self, message: str, *, selected_source_ids: list[str] | None = None) -> str:
        """Answer *message*, append the turn to history, return the reply."""
        if self.chat_model is None:
            raise ResearchError(code="config_missing", message="Chat model is not configured.")
        if selected_source_ids is not None and len(selected_source_ids) > _MAX_IMPORTED_SOURCES:
            raise ResearchError(
                code="config_invalid",
                message=f"Too many imported sources: {len(selected_source_ids)} (max {_MAX_IMPORTED_SOURCES}).",
            )
        result = self._load_result()
        prompt = self._build_prompt(message, result, selected_source_ids=selected_source_ids)
        try:
            reply = self.chat_model.complete(prompt)
        except ResearchError:
            raise
        except Exception as exc:
            raise ResearchError(code="llm_call_failed", message=f"chat LLM call failed: {exc}") from exc
        now = utc_now_iso()
        self._append({"role": "user", "content": message, "created_at": now})
        self._append({"role": "assistant", "content": reply, "created_at": now})
        return reply

    # ── internals ───────────────────────────────────────────────────────

    def _load_result(self) -> dict[str, Any]:
        result_path = self.task_dir / "result.json"
        if not result_path.exists():
            raise ResearchError(
                code="runtime_error", message=f"No result found for chat: {self.task_dir.name}"
            )
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ResearchError(code="runtime_error", message=f"Cannot read task result: {exc}") from exc
        # result.json exists from task creation (status "running"), so gate
        # explicitly: chat is a post-research behavior, not a live companion.
        if result.get("status") != "completed":
            raise ResearchError(
                code="runtime_error",
                message=f"Task {self.task_dir.name} is not finished; chat is available after completion.",
            )
        return result

    def _append(self, message: dict[str, Any]) -> None:
        try:
            with self._history_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(message, ensure_ascii=False) + "\n")
        except OSError as exc:
            raise ResearchError(
                code="file_write_error", message=f"Cannot persist chat history: {exc}"
            ) from exc

    def _build_prompt(
        self,
        message: str,
        result: dict[str, Any],
        *,
        selected_source_ids: list[str] | None,
    ) -> str:
        context = _render_research_context(result, selected_source_ids=selected_source_ids)
        parts = [_SYSTEM_PROMPT, "", context, ""]
        history = self.history()
        if history:
            parts.append("[Conversation so far]")
            for entry in history:
                speaker = "User" if entry.get("role") == "user" else "Assistant"
                parts.append(f"{speaker}: {entry.get('content', '')}")
            parts.append("")
        parts.append(f"[New question]\n{message}")
        return "\n".join(parts)


def _render_research_context(
    result: dict[str, Any],
    *,
    selected_source_ids: list[str] | None,
) -> str:
    """Render the static grounding block from a task result.

    ``selected_source_ids`` is the imported set (NotebookLM-style): a non-None
    value narrows the block to those sources and the findings citing them —
    an explicit empty list imports nothing. ``None`` keeps everything
    (backward compat with the old select-all default).
    """
    curator = result.get("curator_output") or {}
    sources = [s for s in curator.get("sources", []) if isinstance(s, dict)]
    findings = [f for f in curator.get("findings", []) if isinstance(f, dict)]
    sections = [s for s in curator.get("sections", []) if isinstance(s, dict)]

    if selected_source_ids is not None:
        wanted = set(selected_source_ids)
        sources = [s for s in sources if s.get("source_id") in wanted]
        findings = [f for f in findings if wanted.intersection(f.get("source_ids") or [])]
        # Sections are already curated prose; keep them regardless of the
        # source selection — they answer the subtasks, not one source.

    lines = ["[Research context]", f"Research question: {result.get('question', '')}"]
    if curator.get("summary"):
        lines.append(f"Summary: {curator['summary']}")

    report_budget = _MAX_CONTEXT_CHARS // 2
    for section in sections:
        heading = str(section.get("heading", ""))
        text = str(section.get("text", ""))
        if report_budget - len(text) < 0:
            break
        report_budget -= len(text)
        lines.append(f"Report — {heading}: {text}")

    if sources:
        lines.append("Sources:")
        numbers = {source.get("source_id"): f"[S{index}]" for index, source in enumerate(sources, start=1)}
        for source in sources:
            # The raw source_id rides along so the report chapters' inline
            # [src_x] citations stay resolvable next to the [S#] numbering.
            lines.append(
                f"  {numbers[source.get('source_id')]} ({source.get('source_id', '')}) "
                f"{source.get('title', '')} — {source.get('url', '')}"
            )

    budget = _MAX_CONTEXT_CHARS
    if findings:
        lines.append("Findings:")
        for finding in findings:
            text = str(finding.get("text", ""))
            if budget - len(text) < 0:
                logger.info("chat context budget exhausted; dropping remaining findings")
                break
            budget -= len(text)
            cited = " ".join(numbers[sid] for sid in finding.get("source_ids") or [] if sid in numbers)
            prefix = f"[{finding.get('finding_id', '')}] " if finding.get("finding_id") else ""
            lines.append(f"  {prefix}- {text} ({cited})" if cited else f"  {prefix}- {text}")
    if len(lines) == 2:
        lines.append("(No research findings are available for this task.)")
    return "\n".join(lines)
