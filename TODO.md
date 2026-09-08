# Future Upgrades

This document collects complex capabilities discussed during v1 design but intentionally deferred. V1 should stay focused on separate Local RAG and Web Research tasks, read-only Knowledge Base ingestion, a local Web Report File, simple task history, and deterministic implementation phases.

## Research Workflow

- Combined Local + Web research workflow.
  V1 keeps Local RAG and Web Research as separate task modes. This keeps implementation simple, but it also means Web Research cannot use the user's existing local knowledge to improve search strategy, and the user does not get one unified report that combines local knowledge with network research. A future version may add a true combined workflow where Local Results can inform Web Research, Web Research can compare against local knowledge, and the final output can explicitly reconcile both source sets.

- Local-aware Curator.
  Since ADR-0046, the Planner receives Prior Knowledge (a one-time local retrieval slice) before creating Web subtasks. The Curator still does not see local knowledge: a future version may allow Curator to include clearly labeled Local Results alongside Web Findings in the final synthesis. This should preserve provenance so local source paths and web source URLs stay distinguishable.

- Parent task for `both`.
  V1 `research-agent both "question"` is only a CLI convenience that creates one Local task and one Web task. A future version may introduce a parent task that groups both children, tracks aggregate status, and presents a combined result view.

- Combined report.
  V1 does not merge Local Results and Web Research output. A future version may generate a combined report with separate local/web sections, source provenance, and explicit comparison.

- More advanced plan revision.
  V1 Plan Revision appends new pending subtasks and allows the Supervisor to mark existing pending subtasks as `skipped` via `SupervisorOutput.skip_subtask_ids`. If the initial plan is badly wrong, this helps but the system still cannot modify, merge, reorder, or re-score existing subtasks. Future versions may allow Planner to revise subtask questions, merge overlapping subtasks, reorder execution priority, or re-score subtasks based on accumulated evidence.

- Richer Research Gap model.
  V1 stores `research_gaps: list[str]`. A future version may add structured gap fields such as severity, blocking status, affected subtask, suggested query direction, and resolution status.

- Per-role model configuration UI.
  V1 reserves the config structure for per-role model overrides under `[chat_model.<role>]` sections (see ADR-0009), defaulting all roles to the global `[chat_model]` when omitted. The setup flow does not expose per-role configuration. A future version may add per-role model selection in the Web UI settings page and CLI init flow, along with per-role temperature, context window, and cost controls.

## Evidence And Curation

- Claim/evidence-set model.
  V1 uses lightweight `Finding.source_ids`. A future version may add explicit Claim, EvidenceSet, quote spans, confidence, contradiction status, and source-quality metadata.

- Conflict handling.
  V1 does not implement a dedicated evidence-conflict workflow. A future version may detect conflicting findings, route back to research, and surface unresolved conflicts in the final report.

- Citation granularity.
  V1 links Findings to source records only. A future version may support paragraph-level citations, quote spans, page numbers for PDFs, and exact source offsets in Web Reports.

- Final Check node.
  V1 removed a separate Final Check node. A future version may add a post-curation validator for missing citations, unsupported findings, report completeness, or style checks if Supervisor + Curator is not sufficient.

## Knowledge Base

- Knowledge Base editing and management.
  V1 ingestion is read-only. Future versions may support adding tags, updating frontmatter, merging notes, moving files, deleting duplicates, or reorganizing directories, but only behind explicit user actions.

- Incremental index update command.
  V1 exposes `kb status` and `kb rebuild`. Future versions may add `kb update`, `kb clean`, `kb delete`, `kb inspect`, or background incremental indexing.

- Automatic or one-click index refresh.
  V1 Local RAG fails when indexes are missing, stale, building, or failed, and tells the user to run `research-agent kb rebuild`. This is simple and explicit, but the user experience is rough when files changed slightly. A future version may support automatic incremental updates, or make `research-agent local` detect stale indexes and offer a one-step rebuild-and-retry flow instead of only failing.

- Better local parsers.
  V1 uses lightweight Markdown parsing, `pypdf`, and `trafilatura`. Future versions may add OCR, table extraction, complex PDF layout reconstruction, high-fidelity Markdown rendering, richer HTML DOM preservation, and attachment handling.

- Knowledge graph and backlinks.
  V1 parses lightweight links but does not build a full knowledge graph. Future versions may add graph exploration, backlink-aware retrieval, and relationship-aware ranking.

## Retrieval And Web Tools

- Local KB as a Web Research tool (`local_kb_search`).
  Since ADR-0046, the Planner receives a one-time Prior Knowledge slice at task start, but the research loop cannot query the Knowledge Base mid-run. A future version may register `local_kb_search` in the Web ToolRegistry (reusing `retrieve_local_chunks`) so the agent can check local notes with new queries formulated only after seeing web findings — the read side of the deposit loop. Deferred until usage signals justify it: (1) the vault grows via deposits to a size where the initial Top-5 slice visibly misses relevant local material, or (2) Planner output shows it failing to use local knowledge it should have had. A cheaper intermediate step is re-retrieving and injecting local context at plan-revision boundaries, which captures most of the adaptivity without touching the tool registry.

- Earlier URL deduplication.
  V1 deduplicates URLs at the Curator output stage only. During execution, repeated URLs may still create separate WebSource records and source snapshots. A future version may canonicalize and deduplicate URLs at the Tool Gateway or ResearchExecutor level to reduce redundant fetches and storage.

- Multi-engine search and reranking.
  V1 defaults to Tavily through a Search Provider interface. Future versions may add multiple search providers, result fusion, reranking, domain allow/deny lists, and source-quality scoring.

- Browser automation.
  V1 uses HTTP fetch/extract only. Future versions may add browser automation for pages that require rendering, interaction, login, or JavaScript execution.

- Large-scale crawling.
  V1 is not a crawler. Future versions may add bounded crawl policies, sitemap support, robots-aware behavior, crawl queues, and source freshness checks.

- Rich document export.
  V1 outputs Markdown Web Reports only. Future versions may add PDF, HTML, DOCX, slides, or publishable bundles.

## Task History And Memory

- CLI task detail and show commands.
  V1 Web UI Tasks Page supports clicking task rows to navigate to result pages. The CLI `task list` remains summary-only. Future versions may add `task show <task_id>` to the CLI for viewing task results, progress history, and error details from the command line.

- Task deletion and retention policies.
  V1 does not delete task records, artifacts, or reports. Future versions may add safe deletion, retention limits, archive/export, and cleanup commands.

- Memory layer from Task History.
  V1 treats Task History as history only. Future versions may extract durable preferences, recurring topics, project facts, or prior research context as a memory layer for later tasks.

- Full task recovery from checkpoints.
  V1 persists Blackboard snapshots for diagnostic display on crash (see ADR-0005) and marks orphaned running tasks as failed on startup (see ADR-0003), but does not resume LangGraph graph execution from a checkpoint. Future versions may implement full checkpoint-based task resumption so interrupted Web Research tasks can continue from the last Supervisor decision point.

- Task queues and broader concurrency.
  V1 allows one active Local task and one active Web task, plus one Web task's internal subtask concurrency. Future versions may add queues, multiple active tasks per family, priorities, cancellation, and scheduling.

## Interfaces

- Web UI Run Both action.
  V1 Web UI starts Local and Web separately. A future version may add a Run Both action once parent task semantics or grouped results exist.

- Machine-readable CLI output.
  V1 CLI is human-readable only. Future versions may add `--json`, structured event streaming, or shell-friendly output modes.

- User-configurable prompts.
  V1 stores Planner, ResearchExecutor, Supervisor, Curator, and Schema Repair prompts as code constants or builder functions. This keeps prompts versioned with code, but users cannot tune research style, source preferences, report tone, or role behavior. Future versions may support prompt overrides through user config, a prompt directory, or named prompt profiles, while preserving schema constraints and safe defaults.

- Pagination and filtering.
  V1 lists all finished tasks. Future versions may add pagination, filtering by mode/status/date, search, sorting controls, and saved views.

## Error Handling

- Finer-grained error codes.
  V1 uses coarse error codes such as `model_error`, `tool_error`, and `runtime_error` that each cover multiple failure scenarios. For example, `model_error` covers API key invalid, provider unreachable, rate-limited, and timeout — but the user action differs significantly ("fix your config" vs "try again later"). A future version may split these into distinct codes such as `model_auth_error`, `model_unavailable`, `model_rate_limited`, `model_timeout`, `search_auth_error`, `search_unavailable`, `tool_timeout`, `tool_fetch_failed`, and `tool_extraction_failed`, so the CLI and Web UI can render actionable guidance instead of generic failure messages.

## Deployment And Collaboration

- Multi-user accounts and permissions.
  V1 is single-user and local-first. Future versions may add accounts, teams, remote access, per-vault permissions, and collaborative workflows.

- Remote storage or sync.
  V1 stores everything on the local machine. Future versions may add cloud sync, remote databases, shared workspaces, or backup/restore.

- Background daemon.
  V1 avoids a required daemon; CLI can stream in-process and Web UI uses local FastAPI/SSE. Future versions may add a long-running daemon for queues, scheduled indexing, task recovery, and notifications.

## Engineering Tooling

- Advanced debug trace.
  V1 default task history does not store full prompts, completions, provider raw responses, hidden reasoning, or full executor scratchpads. Future versions may add an explicit Debug Trace mode for diagnosis.

- Live provider test suite.
  V1 default tests are deterministic and offline. Future versions may add managed live-provider test profiles, recorded fixtures, or nightly integration checks.

- Alternate package/workspace tooling.
  V1 uses `uv` for Python and npm for Web UI. Future versions may revisit monorepo tooling, pnpm, task runners, or release automation if the project grows.
