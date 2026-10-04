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
import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from research_agent.core.chat_index import TaskChatIndex
from research_agent.core.errors import ResearchError
from research_agent.core.ids import utc_now_iso
from research_agent.core.providers import ChatModelClient

logger = logging.getLogger(__name__)

_HISTORY_FILE = "chat.jsonl"

_SYSTEM_PROMPT = (
    "You are a research assistant discussing a completed research task.\n"
    "- Ground your answer in the research context below (question, summary, findings, sources, "
    "imported excerpts) and cite sources by their [S1]-style numbers where you rely on them.\n"
    "- You may also think for yourself and combine your own knowledge when the context is "
    "incomplete — but say which parts come from the research and which are your own knowledge.\n"
    "- Evidence tools are available when you need more: call one per turn (each at most twice "
    "per question); after the system runs it you will see the results and can continue.\n"
    "- Never invent research findings or sources; if neither the context nor your knowledge "
    "suffices, say so plainly."
)

# R-294: native function calling for the chat evidence actions — the tool
# descriptions carry the when-to-use guidance (no first-line protocol left).
_CHAT_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_sources",
            "description": "Dig further in the original text of the user-imported sources for this task. Use when the imported excerpts miss a detail the sources likely contain.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "What to look for in the imported sources"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Run a new web search for fresh evidence outside the task. Cite results as [W#].",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_page",
            "description": "Fetch one web page or PDF in full by URL. Cite it as [R#].",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "local_search",
            "description": "Search the user's local knowledge vault (personal notes). Cite notes as [L#].",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
]

_TOOL_KINDS = {"search_sources": "SEARCH", "web_search": "WEB", "read_page": "READ", "local_search": "LOCAL"}

# 1 initial answer + up to 4 evidence-action rounds (R-292/R-293).
_MAX_CHAT_ROUNDS = 5
_MAX_ACTIONS_PER_KIND = 2
_MAX_ACTIONS_TOTAL = 4
_EVIDENCE_READ_CHARS = 8_000


class ToolCaller(Protocol):
    def call(self, workflow: str, function_call: dict[str, Any]) -> Any:
        ...


@dataclass(frozen=True)
class ChatToolbox:
    """Evidence actions for the chat loop (R-293). The gateway is the same
    ToolGateway the research executor uses, and the retriever is the vault
    hybrid retriever. Action results land in chat evidence only — never in
    the frozen research artifacts."""

    gateway: ToolCaller | None = None
    local_retriever: Any | None = None

# Hard caps so a huge report cannot blow the chat context window. Findings
# and report sections are each capped separately (additive in the worst
# case); findings drop oldest-subtask-first beyond their budget.
_MAX_CONTEXT_CHARS = 24_000
# R-283: the References card imports sources explicitly (NotebookLM-style);
# 50 is the per-conversation import ceiling, enforced front and back.
_MAX_IMPORTED_SOURCES = 50


def build_default_chat_toolbox(service: Any, config: Any) -> ChatToolbox:
    """Assemble the production ChatToolbox: the shared ToolGateway (same tool
    registry/runner/providers as the research executor) plus the vault hybrid
    retriever. Kept in core.chat to avoid an api→web.tools assembly duplicate."""
    from research_agent.core.service import build_local_retriever, build_shared_tool_gateway

    gateway = build_shared_tool_gateway(config, service.config_path)
    retriever = build_local_retriever(
        config=config, config_path=service.config_path, workspace=service.workspace
    )
    return ChatToolbox(gateway=gateway, local_retriever=retriever)


class TaskChatService:
    """Answer follow-up questions against one finished task's artifacts."""

    def __init__(
        self,
        *,
        task_dir: Path,
        chat_model: ChatModelClient | None,
        embedding_client: Any | None = None,
        toolbox: ChatToolbox | None = None,
    ) -> None:
        self.task_dir = Path(task_dir)
        self.chat_model = chat_model
        self.embedding_client = embedding_client
        self.toolbox = toolbox or ChatToolbox()

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
        excerpts: list[dict[str, Any]] = []
        index = None
        seen_chunks: set[str] = set()
        if selected_source_ids and self.embedding_client is not None:
            # R-285: imported sources' original text is retrieved from the
            # task-local index (built idempotently, never the global KB).
            index = TaskChatIndex(self.task_dir, self.embedding_client)
            index.build_imports(result, selected_source_ids)
            excerpts = index.retrieve(message, selected_source_ids)
            seen_chunks = {chunk["chunk_id"] for chunk in excerpts}
        # R-292/R-293/R-294: grounded-but-combining loop with evidence actions
        # via native function calling (complete_with_tools). Action results
        # live in chat evidence only.
        caller = getattr(self.chat_model, "complete_with_tools", None)
        if caller is None:
            raise ResearchError(
                code="config_missing",
                message="Chat model does not support tool calling (complete_with_tools).",
            )
        evidence_blocks: list[str] = []
        action_counts = {"SEARCH": 0, "WEB": 0, "READ": 0, "LOCAL": 0}
        earlier = self._load_evidence_summaries()
        reply = ""
        for round_num in range(_MAX_CHAT_ROUNDS):
            prompt = self._build_prompt(
                message, result, selected_source_ids=selected_source_ids,
                excerpts=excerpts, evidence_blocks=evidence_blocks, earlier_evidence=earlier,
            )
            try:
                turn = caller(prompt, tools=_CHAT_TOOLS)
            except ResearchError:
                raise
            except Exception as exc:
                raise ResearchError(code="llm_call_failed", message=f"chat LLM call failed: {exc}") from exc
            if not turn.tool_calls:
                reply = turn.text
                break
            name, arguments = turn.tool_calls[0]
            kind = _TOOL_KINDS.get(name)
            if kind is None:
                # Unknown tool: force a plain answer next turn.
                evidence_blocks.append(f"[Unknown evidence tool {name!r} — answer in plain text.]")
                continue
            if round_num == _MAX_CHAT_ROUNDS - 1:
                # R-306: out of rounds while the model still wants evidence.
                # The hint must actually reach the model, so make one final
                # tools-free call — a tool_calls ChatTurn carries empty text
                # and must never be persisted as the reply.
                evidence_blocks.append("[Round budget exhausted — answer now in plain text.]")
                final_prompt = self._build_prompt(
                    message, result, selected_source_ids=selected_source_ids,
                    excerpts=excerpts, evidence_blocks=evidence_blocks, earlier_evidence=earlier,
                )
                turn = caller(final_prompt, tools=[])
                reply = turn.text or "(The answer budget ran out before a final answer was produced. Please ask again.)"
                break
            argument = str(arguments.get("query") or arguments.get("url") or "")
            if action_counts[kind] >= _MAX_ACTIONS_PER_KIND or sum(action_counts.values()) >= _MAX_ACTIONS_TOTAL:
                evidence_blocks.append("[Evidence budget exhausted — answer with what you have.]")
                continue
            action_counts[kind] += 1
            block = self._run_evidence_action(kind, argument, index, selected_source_ids, seen_chunks, excerpts)
            if block is not None:
                evidence_blocks.append(block)
            self._append_evidence({"kind": kind.lower(), "argument": argument})
        now = utc_now_iso()
        self._append({"role": "user", "content": message, "created_at": now})
        self._append({"role": "assistant", "content": reply, "created_at": now})
        return reply

    # ── internals ───────────────────────────────────────────────────────

    def _run_evidence_action(
        self,
        kind: str,
        argument: str,
        index: Any,
        selected_source_ids: list[str] | None,
        seen_chunks: set[str],
        excerpts: list[dict[str, Any]],
    ) -> str | None:
        """Run one evidence action; return a prompt block (None = the result
        rides an existing block, e.g. fresh SEARCH excerpts)."""
        if kind == "SEARCH":
            if index is None or not selected_source_ids:
                return "[SEARCH unavailable: no imported sources indexed.]"
            fresh = [
                chunk for chunk in index.retrieve(argument, selected_source_ids)
                if chunk["chunk_id"] not in seen_chunks
            ]
            if not fresh:
                return "[No additional excerpts found for that query — answer with what you have.]"
            seen_chunks.update(chunk["chunk_id"] for chunk in fresh)
            excerpts.extend(fresh)
            return None
        if kind == "WEB":
            if self.toolbox.gateway is None:
                return "[WEB unavailable in this deployment.]"
            result = self.toolbox.gateway.call(
                "web_research", {"name": "web.search", "arguments": {"query": argument, "max_results": 5}}
            )
            lines = [f'[Evidence W: web.search "{argument}"]']
            for item in (getattr(result, "data", {}) or {}).get("results", [])[:5]:
                lines.append(f"- {item.get('title', '')} — {item.get('url', '')}: {str(item.get('content', ''))[:300]}")
            if len(lines) == 1:
                lines.append("(no results)")
            return "\n".join(lines)
        if kind == "READ":
            if self.toolbox.gateway is None:
                return "[READ unavailable in this deployment.]"
            tool = "web.download_pdf" if argument.lower().split("?")[0].endswith(".pdf") else "web.fetch_extract"
            result = self.toolbox.gateway.call("web_research", {"name": tool, "arguments": {"url": argument}})
            text = str((getattr(result, "data", {}) or {}).get("text", ""))[:_EVIDENCE_READ_CHARS]
            return f"[Evidence R: {tool} {argument}]\n{text or '(no text extracted)'}"
        if kind == "LOCAL":
            if self.toolbox.local_retriever is None:
                return "[LOCAL unavailable: vault retrieval not configured.]"
            chunks = self.toolbox.local_retriever(argument) or []
            lines = [f'[Evidence L: local vault "{argument}"]']
            for chunk in chunks[:5]:
                text = getattr(chunk, "text", "") or ""
                path = getattr(chunk, "source_path", "") or ""
                lines.append(f"- ({path}) {text[:400]}")
            if len(lines) == 1:
                lines.append("(no local notes matched)")
            return "\n".join(lines)
        return None

    @property
    def _evidence_path(self) -> Path:
        return self.task_dir / "chat_evidence.jsonl"

    def _append_evidence(self, record: dict[str, Any]) -> None:
        try:
            with self._evidence_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({**record, "created_at": utc_now_iso()}, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("chat evidence append failed: %s", exc)

    def _load_evidence_summaries(self) -> list[str]:
        if not self._evidence_path.exists():
            return []
        summaries: list[str] = []
        try:
            for line in self._evidence_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                record = json.loads(line)
                summaries.append(f"{record.get('kind', '?')}: \"{record.get('argument', '')}\"")
        except (json.JSONDecodeError, OSError):
            return []
        return summaries[-20:]

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
        excerpts: list[dict[str, Any]] | None = None,
        evidence_blocks: list[str] | None = None,
        earlier_evidence: list[str] | None = None,
    ) -> str:
        context = _render_research_context(result, selected_source_ids=selected_source_ids)
        if excerpts:
            blocks = ["[Imported sources — retrieved excerpts]"]
            for chunk in excerpts:
                blocks.append(f"[{chunk.get('source_id', '')}] {chunk.get('title', '')}: {chunk.get('text', '')}")
            context = context + "\n\n" + "\n\n".join(blocks)
        if evidence_blocks:
            context = context + "\n\n" + "\n\n".join(evidence_blocks)
        if earlier_evidence:
            context = context + "\n\n[Earlier evidence from this conversation]\n" + "\n".join(earlier_evidence)
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
