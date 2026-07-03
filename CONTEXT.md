# Research Agent

This context defines the domain language for a research agent that shows local knowledge matches alongside an independent web research workflow that writes a local Web Report File.

## Language

**Local Research**:
Research over user-approved local sources such as Markdown notes, text files, PDFs, HTML files, and previously saved knowledge. It is scoped to configured local collections, not arbitrary full-disk search.
_Avoid_: desktop search, local browsing

**Local Source**:
A configured local file that can be used as research evidence. The initial source set is Markdown, plain text, PDF, and HTML.
_Avoid_: local file, attachment

**Web Research**:
Research over network sources such as search results, webpages, and online documents. It runs as an independent workflow from Local Research in the initial product.
_Avoid_: online RAG, internet lookup

**Web Source**:
A network source metadata record collected through search, direct URL retrieval, content extraction, or downloaded documents. V1 fields are `source_id`, `title`, `url`, and `fetched_at`; extracted source text is stored separately as a Web Source Snapshot. It excludes authenticated browsing, browser automation, and anti-scraping workarounds.
_Avoid_: browser session, website interaction

**Web Source Snapshot**:
The extracted text snapshot saved for a Web Source inside task files. It stores the full extracted source text separately from the `WebSource` metadata record as a local internal artifact, but it is not included in the Web Report File body.
_Avoid_: webpage archive, report content

**Web Research Pipeline**:
The initial Web Research flow of query, search, fetch, extract, and record source evidence. It uses httpx for fetching, trafilatura for HTML extraction, and pypdf for PDF text extraction, and does not include multi-engine fusion, complex reranking, browser automation, complex PDF layout reconstruction, table extraction, or large-scale crawling in v1.
_Avoid_: crawler, web agent

**Search Provider**:
A configurable Web Research dependency that returns search results through the Tool Gateway. The initial product uses Tavily with provider and API key configuration only.
_Avoid_: search engine, web backend

**Local RAG Research Workflow**:
The independent flow that finds and presents relevant existing content from the configured Knowledge Base, Local Sources, and prebuilt Local RAG indexes. It uses hybrid retrieval (FTS5 keyword + ChromaDB vector with RRF fusion), optionally augments retrieved chunks into an LLM prompt, and generates a natural-language summary via the `local_summarizer` role model when one is configured. When no chat model is available, it falls back to raw-chunk display. It does not call Web Research tools and does not produce a Web Report File in v2.
_Avoid_: local-first research, local search mode

**Web Research Workflow**:
The independent workflow that researches a question using network search, fetch, and extraction. It does not call Local RAG during execution.
_Avoid_: online mode, web search mode

**Research Workflow Boundary**:
The task-level boundary that keeps Local RAG Research and Web Research as separate execution modes. A Local RAG task does not run Web Research, and a Web Research task does not receive Local Results or Knowledge Base context.
_Avoid_: research scope, permission prompt

**Knowledge Base**:
The user's durable local collection of notes, source records, metadata, and searchable indexes. It is the long-term home for saved knowledge, not merely a transient retrieval cache.
_Avoid_: database, vector store, memory

**Markdown Vault**:
A folder of Markdown files that serves as the canonical source for saved knowledge. Search indexes, vector stores, and query databases are derived from it and can be rebuilt.
_Avoid_: note database, storage backend

**Frontmatter**:
Structured metadata stored at the top of a Markdown note. It carries note-level fields such as title, tags, dates, sources, confidence, and status.
_Avoid_: header, properties

**Derived Index**:
A rebuildable retrieval or query structure generated from the Markdown Vault, such as SQLite FTS5 full-text indexes and a ChromaDB persistent vector index (stored under ``indexes/chroma/``). It is not the canonical source of knowledge.
_Avoid_: source of truth, knowledge store

**Knowledge Base Ingestion**:
The read-only process that scans a configured Markdown Vault, parses note metadata and structure, chunks content, builds full-text and vector indexes, records file metadata, and supports incremental updates. V1 uses lightweight Markdown parsing for frontmatter, headings, Markdown links, and wikilinks, reads plain text directly, uses `pypdf` for local PDFs, and uses `trafilatura` for local HTML. It does not rewrite, move, merge, tag, delete, or otherwise modify existing notes; v1 stale checks compare path, mtime, and file size.
_Avoid_: import, migration

**Chunk**:
A traceable retrieval unit derived from a Markdown note or Local Source. V1 chunks Markdown by heading first and then by paragraphs within each section; plain text, PDF, and HTML use paragraph-based chunking after text extraction. Chunking prefers not to split paragraphs, targets about 3000 characters, hard-splits only when a single accumulated chunk would exceed about 5000 characters, and uses no fixed overlap. Each chunk records `chunk_id`, `source_path`, `heading_path`, `start_offset`, `end_offset`, and `text` so Local RAG can produce source-linked Local Results.
_Avoid_: text fragment, embedding row

**Local Result**:
A Local RAG display item containing relevant content and its source file path. It is a simple view into existing local knowledge rather than a generated local report, with v1 defaulting to the top 10 results.
_Avoid_: local finding, local report item

**Link Context**:
Lightweight Markdown and wikilink relationship data used to expand or explain Local RAG results. It is not a full knowledge graph or link-management system in the initial product.
_Avoid_: knowledge graph, backlink editor

**Source Record**:
A record of a source used during research, such as a webpage, local file, note, or document. It preserves enough identity and retrieval metadata to revisit or audit the source later, without requiring source-quality scoring in the initial product.
_Avoid_: reference, link

**Finding**:
A key discovery or conclusion produced by Web Research. V1 fields are `finding_id`, `subtask_id`, `text`, and `source_ids`, keeping only a lightweight finding-to-source relationship rather than a claim/evidence-set model.
_Avoid_: claim, insight

**Evidence**:
A source link that supports or contextualizes a Finding. In Web Research reports, Evidence is represented as source-number references backed by the Sources list rather than paragraph-level citations.
_Avoid_: citation, evidence set

**Unsupported Finding**:
A Finding without supporting Evidence. It can be shown as needing follow-up but should not be presented as fully supported.
_Avoid_: unverified claim, assumption

**Research Task**:
A user request container for one research question and one selected execution mode, either Local RAG or Web Research.
_Avoid_: session, run

**Active Research Task Family**:
The v1 concurrency boundary for user-started tasks. Local RAG and Web Research are separate task families and may run concurrently as separate tasks, but v1 allows only one active Local RAG task and one active Web Research task at a time. This does not limit Web Research's internal concurrent subtask execution.
_Avoid_: global task lock, daemon worker

**Research ID Policy**:
The v1 identifier convention for persisted objects. `task_id` uses `task_yyyymmdd_hhmmss_<random6>`, Web subtasks use task-local `st_1`, `st_2`, Web sources use task-local `src_1`, `src_2`, findings use task-local `f_1`, `f_2`, and Local RAG chunks use internal `chunk_<short_hash>` IDs derived from source path, offsets, mtime, and size.
_Avoid_: model-generated id, distributed id

**Research Timestamp**:
A persisted timestamp stored as UTC ISO 8601 with `Z`, such as `2026-06-23T10:30:00Z`. UI may render local time, but storage and APIs use UTC for fields such as `created_at`, `fetched_at`, and `built_at`.
_Avoid_: local time storage, ambiguous datetime

**Research Task State**:
The shared structured workspace for one Web Research Task. It acts as a Blackboard where research roles read and write structured workflow facts through role-specific slices rather than passing private natural-language context between agents.
_Avoid_: memory file, agent context

**Blackboard**:
The shared Web Research state around which research roles coordinate. Planner writes plans, Executor Nodes write sources and candidate findings, Supervisor writes routing decisions, and Curator writes Research Output without direct role-to-role chat.
_Avoid_: chat history, shared prompt

**LangGraph Checkpoint**:
The runtime checkpoint that records LangGraph execution position and full graph state after each node completes. It is stored via `SqliteSaver` in a SQLite database (`checkpoints.sqlite`) under the task workspace, replacing the V1 manual per-round `blackboard_snapshot.json`. Checkpoints enable pause/resume across process restarts. They are distinct from Research Task State, which carries product-level research semantics, and from `events.jsonl`, which is the append-only progress display log.
_Avoid_: task state, task history

**LangGraph StateGraph**:
The declarative graph definition that replaces the manual `while` loop in the Web Research runner. Nodes represent role invocations (`plan_node`, `execute_node`, `supervise_node`, `plan_revision_node`, `curate_node`); edges represent data flow and conditional routing based on `SupervisorOutput.route`. The route guard (retrieval limit enforcement) moves from inline code to `config.recursion_limit`. Node functions continue to call `_emit` for progress events — the graph layer is orthogonal to the EventStream.
_Avoid_: while loop, runner loop

**State Reducer**:
A function attached to each field of the LangGraph `TypedDict` state that defines how concurrent or sequential updates to that field are merged. V1 uses `operator.add` for list-append fields (`subtasks`, `findings`, `sources`, `research_gaps`, `route_history`, `planner_outputs`) and last-write-wins for scalar fields (`original_question`, `research_title`, `curator_output`, `retrieval_round`). Reducers replace the current `@dataclass` mutation methods (`add_planner_output`, `merge_executor_output`, `apply_supervisor_output`).
_Avoid_: merge strategy, state mutation

**Context Builder**:
The internal component that constructs role-specific context slices from Research Task State. It centralizes context selection so research roles do not each hand-roll state access.
_Avoid_: prompt helper, state reader

**Research Saturation**:
The point where the Supervisor judges that additional Web Research tool calls are unlikely to materially improve the Research Output. It is the main completion condition for a Web Research Task, bounded by hard limits such as the default maximum of 3 retrieval rounds and user stop actions.
_Avoid_: coverage, completion percentage

**Curation Readiness**:
The Supervisor's determination that the Blackboard is ready for Curator. It requires usable sources, findings that either link to Evidence or are marked unsupported, and a Supervisor route to curation based on Research Saturation or a hard retrieval limit.
_Avoid_: final check, completion score

**Research Gap**:
A missing-information note identified and maintained by the Supervisor during a Web Research Task. In v1 it is represented as plain text in `research_gaps: list[str]` rather than a structured object with blocking or severity fields, and it is workflow-internal context for continuing execution or revising the plan rather than final report content.
_Avoid_: open question, uncertainty

**Task History**:
The persisted record of finished Research Tasks. It can later support memory-like context, but it is not the Knowledge Base and does not replace saved notes; v1 task management lists tasks after they reach `completed` or `failed`. The Web UI Tasks Page supports clicking a task row to navigate to its result page via `GET /api/tasks/{task_id}/result`; the CLI `task list` remains a summary-only view without detail navigation. V1 does not provide task delete actions. The list view displays all finished records with `task_id`, `mode`, `status`, `title_or_question`, and `created_at`, mixing `local` and `web` tasks in one list sorted by `created_at` descending without pagination or a default limit. Task modes are only `local` and `web`; `both` is a CLI convenience command that creates separate `local` and `web` task records rather than a parent task.
_Avoid_: memory, archive

**Tasks Table**:
The core SQLite table for task-history lists. V1 stores `task_id`, `mode`, `status`, `title_or_question`, `created_at`, `completed_at`, optional `report_path`, and `result_path`; progress records are not stored in SQLite and belong only in `events.jsonl`.
_Avoid_: progress event table, report store

**Result File**:
The local `tasks/{task_id}/result.json` file that stores the display result for one task. Local result files store `local_results` with source paths or an error. Web result files store `curator_output` and `report_path` on success, or an error on failure. It does not store full Web source text, raw tool results, prompts, model completions, executor scratchpads, or the full progress event list.
_Avoid_: state file, checkpoint, report file

**Research Error**:
The unified user-facing error object used by CLI, Web API, and `result.json`. V1 stores only `code` and `message`, with codes such as `config_missing`, `busy`, `kb_index_stale`, `model_error`, `tool_error`, `schema_validation_failed`, `runtime_error`, and `file_write_error`; richer exception details belong in logs or Debug Trace.
_Avoid_: stack trace, exception dump

**Default Workspace**:
The globally configured working directory used by Research Agent regardless of the shell directory where commands are launched. It contains local task history, result files, indexes, internal task artifacts, and Web Report Files, with v1 using `tasks/`, `indexes/local/`, `reports/web/`, and `logs/` as the top-level application-managed directories. The launch cwd is not a runtime state root; it is only used during Initialization to resolve user-entered relative paths before absolute paths are saved into User Config.
_Avoid_: current directory, markdown vault

**User Config**:
The user-level TOML configuration file at `%APPDATA%/research_agent/config.toml`. It stores application settings such as the Default Workspace, Knowledge Base path, retrieval limits, `max_concurrent_subtasks`, chat and embedding model base URLs, model names, provider API keys, search provider, index backend, and Web Tool engineering boundaries.
_Avoid_: project config, example config

**Initialization**:
The explicit setup flow that creates User Config before research commands can run. CLI uses `research-agent init`, and Web UI shows setup when User Config is missing. V1 initialization only collects settings, validates required fields, creates the Default Workspace if needed, and writes `%APPDATA%/research_agent/config.toml`; it does not scan the Knowledge Base, build indexes, start services, call providers, or run research.
_Avoid_: implicit defaults, auto setup

**Task Progress**:
The real-time product progress view of a currently running Research Task. It is emitted through Research Progress Stream and Process View rather than persisted as task-management statuses; Task History only records final `completed` or `failed` tasks.
_Avoid_: graph status, node status

**Research Progress Stream**:
The real-time product progress stream emitted while a Research Task runs. It is phase-based: each streamed record is anchored by `phase`, with `event_type` limited to that phase's progress state (`started`, `progress`, `completed`, or `failed`). Each `events.jsonl` line stores one append-only progress display record with top-level `task_id`, `mode`, `phase`, `event_type`, optional `event_subtype`, `created_at`, `message`, `seq`, and `details`; v1 does not add `event_id` or an outer `subtask_id`. Web UI consumes it through SSE, and CLI uses it to display live progress until completion without requiring a v1 daemon concept.
_Avoid_: daemon, raw logs

**EventStream**:
The shared in-process event channel that transports Research Progress Stream records from the runner to consumers (SSE endpoint and CLI). It is backed by a `janus.Queue` (sync/async dual-faced queue) with a max capacity of 1024 events. The runner pushes events via `_emit` to both the queue and `events.jsonl`; consumers read from the queue via `async for`. Events carry a monotonically increasing `seq` integer for deduplication when the consumer first replays missed events from `events.jsonl` before switching to live queue consumption. The queue is created lazily when the first consumer connects and destroyed when the runner finishes. `events.jsonl` remains the persistence and replay layer—it is no longer the transport layer.
_Avoid_: callback, polling, file-watcher

**Progress Event Subtype**:
An optional `event_subtype` field on Research Progress Stream records that classifies progress-scoped events for direct UI rendering without digging into `details.items`. Values include `tool_call`, `finding`, `source`, `subtask_started`, `subtask_completed`, and `subtask_failed`. Phase-boundary events (`started`, `completed`, `failed`) omit `event_subtype`. CLI uses `event_subtype` to select output format; Web UI uses it to pick the appropriate detail card without branching on `details.items[].kind`.
_Avoid_: nested discrimination, item kind parsing

**Event Sequence**:
A monotonically increasing integer `seq` assigned by `_emit` to every Research Progress Stream record. Consumers use it to deduplicate events when the EventStream first replays persisted events from `events.jsonl` and then switches to live queue consumption—any event whose `seq` was already yielded during file replay is skipped from the queue. The counter is per-runner, not global.
_Avoid_: event_id, timestamp ordering

**Runner Registry**:
An in-memory mapping from `task_id` to `StateGraphRunner` held at the API module level. It allows the SSE endpoint (`GET /api/tasks/{task_id}/events`) to look up the live runner for an active task and obtain its `EventStream`. The registry entry is removed via an `on_done` callback invoked when the runner's `run()` method completes. When a task is not found in the registry (already finished or never existed), the SSE endpoint falls back to serving `events.jsonl` as a static file stream.
_Avoid_: global service registry, daemon process

**Progress Item**:
A minimal display-only item inside a Research Progress Stream record's `details.items`. V1 supports `tool_call` with `name` and user-facing `input`, `source` with either `title` plus `url` or a local `path`, and `finding` with `text`. Progress Items are not the source of truth for recovery, routing, Supervisor judgment, or report generation.
_Avoid_: tool result, evidence record, internal state

**Research Phase**:
A product-level phase value used as the primary discriminator in Research Progress Stream records. Local RAG uses `local_rag`. Web Research uses `web_planning`, `web_execution`, `web_supervision`, `web_revision`, and `web_curation`. Phases describe user-visible progress without exposing LangGraph internals. `web_planning` is the first Planner run that creates the initial subtask plan, while `web_revision` is a later Planner run that appends new pending subtasks based on Supervisor-maintained research gaps.
_Avoid_: graph node, checkpoint state

**Debug Trace**:
An explicit diagnostic mode that may preserve fuller model and runtime details for troubleshooting. It is not the default Task History behavior.
_Avoid_: task history, audit log

**Memory Layer**:
A future capability that can extract durable preferences, recurring context, or project facts from Task History. It is not part of the initial Task History boundary.
_Avoid_: task history, knowledge base

**Model Provider**:
An external or local model backend used for planning, execution, synthesis, or embeddings. The initial product only implements `openai_compatible` while keeping the provider field for later expansion.
_Avoid_: LLM, model

**Chat Model**:
The default configured chat model used by Web Research roles and Local RAG summarization when no role-specific override is configured. Configured with provider, model, base URL, and API key.
_Avoid_: role model, agent model

**Embedding Model**:
The configured embedding model used for Knowledge Base indexing and Local RAG retrieval. It is configured with provider, model, base URL, and API key.
_Avoid_: chat model, vector model

**Role Model Slot**:
An optional per-role chat model override that allows Planner, Executor, Supervisor, Curator, and Local Summarizer to use different chat models. V1 reserves the config structure under `[chat_model.<role>]` sections but defaults all roles to the global `[chat_model]` settings when role-specific overrides are absent; the setup flow only collects the global chat model and does not expose per-role configuration. Supported roles: `planner`, `executor`, `supervisor`, `curator`, `local_summarizer`.
_Avoid_: model slot, agent model

**RAG**:
Retrieval-augmented generation used to retrieve relevant source material from the Knowledge Base. In v1 it powers Local Results rather than feeding the Web Research workflow.
_Avoid_: knowledge base, search

**Hybrid Retrieval**:
The initial Local RAG retrieval strategy that combines SQLite FTS5 full-text search (keyword) and ChromaDB vector search (semantic), fuses results via Reciprocal Rank Fusion (RRF, k=60), and returns the top-10 fused, traceable Chunks. Falls back to FTS5-only when no embedding client is available. ChromaDB embedding is batched (32 chunks per request) to stay within API limits. Does not require complex reranking or agentic query rewriting in v1.
_Avoid_: semantic search, reranking

**Planner**:
The Web Research role that turns the original user question into web research goals, subquestions, source strategy, stopping criteria, and an expected report shape. It does not receive Local Results or Knowledge Base context, and it revises the plan only when requested by the Supervisor.
_Avoid_: researcher, search agent

**ResearchSubtask**:
A runtime-normalized unit of Web Research work with `subtask_id`, `question`, and execution `status`. Planner proposes subtask questions, while runtime assigns stable `subtask_id` values such as `st_1` and initial `pending` status before writing subtasks into the Blackboard. Later status updates come from ResearchExecutor results, or the Supervisor may mark pending subtasks as `skipped` via `SupervisorOutput.skip_subtask_ids`. The `question` tells ResearchExecutor what to investigate; v1 does not keep a separate `goal` field because subtask completion is judged by ResearchExecutor and returned through `ExecutorOutput.status`.
_Avoid_: task goal, executor plan

**PlannerOutput**:
The Planner's structured output containing `research_title` and proposed subtask questions. Runtime normalizes those proposals into `ResearchSubtask` records by assigning `subtask_id` and initial `pending` status. PlannerOutput does not include retrieval limits such as `max_retrieval_rounds`; those are runtime configuration boundaries.
_Avoid_: planner config, markdown plan

**PlannerInput**:
The structured input used by Planner. Initial planning receives the original question; Plan Revision receives the original question, current plan, executor outputs, research gaps, and Supervisor's plan revision request.
_Avoid_: planner prompt text, full blackboard

**Executor Node**:
A research execution role that directly executes Planner-created subtasks assigned by the Supervisor through the Tool Gateway. The initial product uses one ResearchExecutor LangGraph node type. A single node invocation may run one or more isolated executor agent runs for Supervisor-selected subtasks, but each subtask run has its own scratchpad and cannot create a separate execution plan, change the research route, or bypass runtime scope checks.
_Avoid_: tool-specific executor, autonomous worker

**Executor Tool Loop**:
The internal ResearchExecutor loop for one assigned subtask. It calls a Web Research tool, appends the structured result to that subtask run's temporary executor context, then decides whether the subtask is complete, needs another tool call, or should return Subtask Failure.
_Avoid_: retrieval round, graph loop

**Executor Scratchpad**:
The temporary ResearchExecutor context used inside one Executor Tool Loop. Each concurrently executed subtask has an isolated scratchpad; scratchpads do not read or mutate each other. Scratchpad content is not fully persisted; only structured tool call records, sources, findings, status, and failure reasons are written to Blackboard or Task History.
_Avoid_: task history, blackboard

**Subtask Failure**:
A structured ResearchExecutor result indicating that an assigned subtask could not be completed after reasonable tool attempts or source failures. The Supervisor owns the follow-up route.
_Avoid_: tool error, task failure

**Tool-Level Transient Failure**:
A temporary failure during a tool call, such as timeout, fetch failure, extraction failure, or transient provider response. Tool Gateway handles same-parameter low-level retries, while ResearchExecutor handles strategic recovery such as changing query, changing URL, skipping a source, or returning Subtask Failure.
_Avoid_: runtime failure, node failure

**Runtime Failure**:
A system-level failure such as invalid configuration, unavailable model provider, unrepaired schema failure, or node code error. LLM schema validation may be repaired one time per role invocation; if the repair fails, it terminates the Web Research Workflow and returns an error instead of being routed as a research gap.
_Avoid_: subtask failure, source failure

**Schema Repair**:
An internal fallback LLM call used when a role output fails parsing or schema validation. It sends only the raw invalid output, validation error, and target schema back to the model to fix format or fields without rerunning the node. V1 allows one repair attempt per role invocation; if the repair fails, the Web Research Workflow terminates with a `schema_validation_failed` error.
_Avoid_: repair node, final check

**Executor Batch**:
A Supervisor-approved set of subtask IDs executed by one ResearchExecutor node invocation. The node may run those subtasks concurrently as isolated executor agent runs, limited by `research.max_concurrent_subtasks` which defaults to `3`, then merge their structured outputs back into the Blackboard before the Supervisor decides the next route.
_Avoid_: parallel agents, background jobs

**ExecutorOutput**:
The structured output of one isolated subtask execution. A ResearchExecutor node invocation may produce multiple `ExecutorOutput` records as `executor_outputs`, one per completed or failed subtask run. V1 fields are `subtask_id`, `status`, `findings`, `sources`, and optional `failure_reason`; it does not include Research Gap suggestions, raw source text, tool raw results, or executor scratchpad content.
_Avoid_: node output, batch output

**Supervisor**:
The routing role that inspects a focused Blackboard slice, controls research state transitions, decides whether tasks need revision or more execution, and determines when evidence is sufficient to move toward curation. Its v1 context contains the original question, the current plan with subtask statuses, and full structured `executor_outputs` including findings, Web source metadata, status, and failure reasons. It does not read full source snapshots, tool raw results, executor scratchpads, or retrieval hard-limit counters in its prompt; hard limits are enforced by the runtime graph layer. It does not create the initial plan, directly gather sources, or decide the fine-grained completion status of an individual subtask; that status is returned by ResearchExecutor.
_Avoid_: planner, executor

**SupervisorOutput**:
The Supervisor's structured routing decision. V1 fields are `route`, `reason`, `next_subtask_ids`, optional `skip_subtask_ids`, optional `plan_revision_request`, `research_gaps: list[str]`, and `saturation`; the graph routes only by `route`, while `saturation` records whether Supervisor believes more Web Research is unlikely to materially improve the output. `skip_subtask_ids` allows the Supervisor to mark pending subtasks as `skipped` so they are not executed and do not count toward retrieval round limits.
_Avoid_: supervisor notes, graph state

**Runtime Route Guard**:
The graph-layer safety check applied after SupervisorOutput and before routing. If Supervisor requests `continue_execution` after `max_retrieval_rounds` is reached, runtime redirects to `curate` when usable findings and sources exist, or to `fail` when they do not.
_Avoid_: supervisor counter, planner budget

**Plan Revision**:
A Planner update to the research plan requested by the Supervisor when new evidence, missing coverage, or poor search direction makes the current plan insufficient. In v1, the plan is the `PlannerOutput.subtasks` list, and Plan Revision appends new `pending` subtasks from the original question, current plan, executor outputs, research gaps, and Supervisor's revision request. Before requesting plan revision, the Supervisor may mark existing pending subtasks as `skipped` via `SupervisorOutput.skip_subtask_ids`; skipped subtasks are not executed and do not count toward retrieval round limits. Plan Revision does not modify or delete existing `completed`, `failed`, or `skipped` subtasks. It reuses the same Planner node, does not impose a separate plan-revision count limit, and does not reset retrieval-round limits.
_Avoid_: replanning, search optimization

**Curator**:
The role that turns completed research into a structured `CuratorOutput` after the Supervisor determines the Blackboard is ready for curation. Its key conclusions must come from Findings and their linked Web Sources through `source_ids` rather than unsupported summarization, and it does not include workflow-internal research gaps in the final report content.
_Avoid_: writer, note agent

**CuratorOutput**:
The final structured Web Research report content produced by Curator before Markdown rendering. V1 fields are `title`, `summary`, `findings`, and `sources`; it does not include workflow-internal `research_gaps`.
_Avoid_: markdown file, draft report

**Research Output**:
The output produced by the Web Research Workflow, represented as a local Web Report File. Local RAG produces Local Results instead of a Research Output in v1.
_Avoid_: final report, answer

**Web Report File**:
A local Markdown file written by Web Research under `reports/web/` immediately after `CuratorOutput` is produced successfully. It contains summary, findings, linked evidence, and the full web source list; it does not include workflow-internal research gaps, does not cite Local Results, and is exposed through `report_path` rather than a download action in v1. A Web Research task is `completed` only after both CuratorOutput generation and Web Report File writing succeed. If writing the file fails, the Web Research task is `failed` with `file_write_error` because the user-visible report file was not created.
_Avoid_: download, deposited note

**Report Filename**:
The user-facing Markdown filename for a Web Research report. V1 uses `{topic_slug}-{yyyy-mm-dd}.md`, where `topic_slug` is derived from the user question or report title, preserves Chinese characters, lowercases English letters, replaces whitespace with hyphens, removes Windows-illegal filename characters, truncates to 80 characters, and appends `-2`, `-3`, and so on when names collide.
_Avoid_: task id filename, random filename

**Process View**:
The UI/CLI view of Web Research execution details such as planner subquestions, search queries, fetched URLs, retrieval rounds, and status. It is separate from the Web Report File and does not appear as a full tool log in the report body.
_Avoid_: report section, debug trace

**Report Template**:
The Markdown structure used by the Web Report File. Local RAG uses a Local Result display rather than this report template.
_Avoid_: local report format, draft note format

**Knowledge Base Index**:
The user-facing index maintenance surface for the configured Markdown Vault. It shows vault path, index status, file and chunk counts, last indexed time, and supports rebuild actions. V1 CLI exposes only `research-agent kb status` and `research-agent kb rebuild`.
_Avoid_: knowledge base management, note management

**Knowledge Base Index Status**:
The user-facing state returned by `kb status`: `missing`, `ready`, `stale`, `building`, or `failed`. Local RAG queries are allowed when status is `ready` or `stale` (FTS5 keyword index is available even if ChromaDB vectors are outdated); `missing`, `building`, and `failed` make Local RAG fail before retrieval and instruct the user to run `research-agent kb rebuild`. V1 stale checks compare indexed file path, mtime, and file size, not hashes.
_Avoid_: partial_success, completed_with_warning

**Capability Surface**:
The complete set of research and Knowledge Base capabilities available through both Web UI and CLI. Each interface may add form-specific helpers, but neither is a reduced version of the other.
_Avoid_: frontend features, CLI features

**Core Service**:
The shared application layer that exposes the Capability Surface to interfaces such as Web UI and CLI. It owns research, Local RAG retrieval, Web Research, and Knowledge Base Index workflows so interfaces do not implement separate behavior. V1 exposes a small use-case surface: `init_config`, `run_local_research`, `run_web_research`, `run_both`, `list_finished_tasks`, `get_kb_status`, and `rebuild_kb_index`.
_Avoid_: backend, API server

**Research Runtime**:
The LangGraph-based execution layer for a Web Research Task. It runs Web Research roles, manages graph state, checkpoints progress, and produces auditable Web Research output.
_Avoid_: core service, agent loop

**Tool Capability**:
A Web Research agent capability such as Web Search, Web Fetch, Web Extract, or Web PDF Download. Tool Capabilities are not private logic embedded inside a single Executor Node.
_Avoid_: executor feature, helper function

**Tool Registry**:
The internal catalog of Web Research agent tools, their names, workflow permissions, and input schemas. Standard function calls resolve against the Tool Registry before execution.
_Avoid_: tool list, plugin registry

**Tool Gateway**:
The Web Research Runtime interface that validates standard function calls before tool execution. It checks tool existence, input schema validity, and workflow permission, then records calls and returns structured tool results; low-level transient retries default to 2. V1 applies wide per-call engineering boundaries. URL deduplication is performed at the Curator output stage rather than at the gateway level.
_Avoid_: tool wrapper, SDK adapter

**Tool Runner**:
The internal executor that invokes a validated tool implementation after Tool Gateway checks pass. It separates validation and policy from the actual tool implementation and enforces tool-specific timeout, response-size, PDF-size, content-type, and extraction boundaries.
_Avoid_: tool gateway, tool adapter

**Web UI**:
The graphical interface for the Capability Surface, optimized for starting Local RAG or Web Research tasks, reviewing Local Results, monitoring Web Research, showing Web Report File paths, browsing task history, and maintaining the Knowledge Base Index.
_Avoid_: dashboard, admin panel

**Web API**:
The minimal local FastAPI surface used by Web UI. V1 exposes setup status/init, Local RAG start, Web Research start, active task lookup, finished task list, task progress SSE, current-run result lookup, Knowledge Base status, and Knowledge Base rebuild. It does not expose a Run Both endpoint, task-history detail endpoint, task delete endpoint, settings editor, or note-management API.
_Avoid_: public API, remote backend

**Setup View**:
The Web UI view shown only when User Config is missing. It supports initial configuration and is not a general Settings page in v1.
_Avoid_: settings page, admin settings

**Research Page**:
The Web UI page with a Local RAG input area, a Web Research input area, and progress views for active Local RAG and Web Research tasks. It does not provide a combined Run Both action; users start Local RAG and Web Research separately if they want both. Local RAG and Web Research can run concurrently as separate tasks, but each task family allows only one active task at a time. Local mode leads to a Local Result Page, and Web mode leads to a Web Report Page.
_Avoid_: chat page, dashboard

**Local Result Page**:
The Web UI result view shown immediately after a Local RAG task completes. It shows `question`, `status`, and stored Local Results with `text`, `source_path`, and optional `heading_path` without rerunning retrieval.
_Avoid_: comparison view, local report

**Web Report Page**:
The Web UI result view shown immediately after a Web Research task completes. It shows `question`, `status`, Process View grouped by phase, Summary, Findings, Sources, and `report_path` for the generated Web Report File. Opening the current result view does not resume Web Research, call tools, regenerate CuratorOutput, or rewrite the Web Report File. If report file writing fails after CuratorOutput succeeds, this page shows the task as `failed` with the `file_write_error` instead of showing a completed task without a report.
_Avoid_: comparison view, merged report

**Tasks Page**:
The Web UI page for listing all finished Research Tasks in one mixed `local` and `web` list sorted by `created_at` descending. Clicking a task row navigates to its result page by calling `GET /api/tasks/{task_id}/result` and rendering the mode-appropriate view (Local Result Page or Web Report Page). Running tasks are shown through the active Research Progress Stream and Process View, not the task-management list; v1 does not include pagination, delete actions, `error_summary`, or report file error columns here.
_Avoid_: history archive, run log

**Knowledge Base Index Page**:
The Web UI page for Local RAG index maintenance. It shows `vault_path`, index status, file count, chunk count, last indexed time, and build or rebuild actions.
_Avoid_: note manager, vault editor

**CLI**:
The command-line interface for the Capability Surface, optimized for starting Local RAG tasks with `local`, Web Research tasks with `web`, starting both independent task families for the same question with `both`, listing finished task history, and maintaining the Knowledge Base Index through `kb status` and `kb rebuild`. It streams phase progress while active commands run, prints human-readable results, renders Research Errors as `[code] message`, and exits non-zero for failed tasks, busy conflicts, invalid setup, index failures, runtime failures, and Web Report File write failures. `both` starts separate Local RAG and Web Research tasks, displays separate final statuses, and exits non-zero if either task fails or Web report file writing fails; it does not create a combined workflow or combined report. The CLI does not expose a generic `research` command, machine-readable JSON output mode, task show/delete commands, `kb update`, `kb clean`, `kb delete`, deposit, or note-editing commands in v1.
_Avoid_: terminal page, limited mode
