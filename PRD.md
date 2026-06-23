# Research Agent V1 Product Requirements Document

## Problem Statement

研究型工作经常需要同时参考本地长期积累的知识库和最新网络资料，但现有流程通常分散在搜索引擎、浏览器、Markdown 笔记、命令行脚本和临时文档之间。用户需要一个本地优先的 Research Agent：既能读取已有 Markdown Vault 并进行 Local RAG 检索，也能通过 Web Research 自动完成规划、搜索、资料提取、监督路由和报告生成，同时保留清晰的来源路径、任务历史和本地文件输出。

V1 的核心问题不是构建一个全自动知识库改造工具，而是提供一个可靠、可追踪、可本地运行的调研工作台，让用户能在 Web UI 和 CLI 中获得同等核心能力。

## Solution

Research Agent V1 提供两个独立任务模式：

1. Local RAG Research：读取用户配置的本地 Knowledge Base，基于预构建索引返回相关内容和源文件路径，不使用 LLM 生成本地摘要，不修改用户知识库。
2. Web Research：基于 LangGraph 状态图和 Blackboard Pattern，由 Planner、ResearchExecutor、Supervisor、Curator 协作完成网络调研，并在本地生成 Markdown Web Report File。

V1 提供 Web UI、CLI、Core Service、Local RAG Index、Web Research Runtime、Task History 和 User Config。Local RAG 与 Web Research 在执行和报告上保持隔离；CLI 的 `both` 只是同时启动两个独立任务，不生成父任务或合并报告。

## Goals

- 支持用户指定 Markdown Vault / Knowledge Base 路径。
- 支持只读 Knowledge Base Ingestion，扫描文件、解析结构、切分 chunk、建立全文索引和向量索引。
- 支持 Local RAG 检索并展示相关内容与 `source_path`。
- 支持 Web Research 的状态图式调研循环：计划、执行、监督、修订、继续执行、整理报告。
- 支持 Web Report File 自动落盘到默认 workspace 的 `reports/web/`。
- 支持 Web UI 和 CLI 访问同一套 Core Service 能力。
- 支持实时进度输出：CLI 直接流式显示，Web UI 通过 FastAPI + SSE 显示。
- 支持 finished task history，记录已完成或失败的 Local/Web 任务。
- 支持用户级配置文件 `%APPDATA%/research_agent/config.toml`。
- 保持 V1 行为简单、可测试、可离线验证。

## Non-Goals

- 不实现 Local RAG 与 Web Research 的融合调研。
- 不让 Web Research 使用 Local Results 作为上下文。
- 不生成 Local + Web 合并报告。
- 不自动改写、移动、合并、删除或重排用户 Markdown Vault。
- 不实现自动知识沉淀到用户 Vault。
- 不实现任务恢复、队列、多用户、云同步或后台 daemon。
- 不实现浏览器自动化、大规模爬虫、多搜索引擎融合或复杂 PDF 版面解析。
- 不实现 CLI JSON 输出、任务删除、CLI task show、完整设置页或 Web UI Run Both。

## User Stories

1. As a researcher, I want to configure a default workspace, so that Research Agent always stores task history, indexes, reports, and logs in one predictable local location.
2. As a researcher, I want to configure my Knowledge Base path, so that Local RAG can retrieve from my existing Markdown Vault and local sources.
3. As a researcher, I want Knowledge Base ingestion to be read-only, so that the agent never unexpectedly changes my long-term notes.
4. As a researcher, I want to rebuild the Local RAG index, so that changed local files become searchable.
5. As a researcher, I want Local RAG to fail when the index is missing or stale, so that I do not unknowingly query outdated index data.
6. As a researcher, I want Local RAG results to show relevant text and source file paths, so that I can open the original material myself.
7. As a researcher, I want to start Web Research from CLI, so that I can run deep research from terminal workflows.
8. As a researcher, I want to start Web Research from Web UI, so that I can monitor research visually.
9. As a researcher, I want Web Research to plan subtasks, so that a broad research question is decomposed before execution.
10. As a researcher, I want ResearchExecutor to execute Planner-created subtasks, so that each subtask has a clear execution target.
11. As a researcher, I want Web Research subtasks to run concurrently within a configured limit, so that research is faster without uncontrolled parallelism.
12. As a researcher, I want Supervisor to inspect the plan and executor outputs, so that the workflow can continue, revise, curate, or fail based on structured state.
13. As a researcher, I want Plan Revision to append new pending subtasks when gaps are found, so that the workflow can recover from incomplete initial planning.
14. As a researcher, I want Curator to generate a structured output only from findings and linked web sources, so that final conclusions remain traceable.
15. As a researcher, I want Web Research to write a Markdown report locally, so that the result is durable and easy to read outside the app.
16. As a researcher, I want Web Research to fail if the report file cannot be written, so that "completed" never means "completed but no report exists".
17. As a researcher, I want progress events grouped by research phase, so that I can understand what the agent is currently doing without reading raw logs.
18. As a researcher, I want finished task history, so that I can see prior Local and Web research tasks.
19. As a researcher, I want Web UI task rows to open mode-appropriate results, so that I can inspect finished task outputs from the app.
20. As a CLI user, I want human-readable output and non-zero exits on failure, so that commands are useful in normal terminal workflows.

## Functional Requirements

### Configuration

- The application must store user config at `%APPDATA%/research_agent/config.toml`.
- Config must include default workspace, Knowledge Base path, chat model settings, embedding model settings, search provider settings, research limits, index backend, and web tool boundaries.
- V1 must support only `openai_compatible` chat and embedding providers.
- V1 must reserve per-role chat model config sections while defaulting all roles to the global chat model.
- `research-agent init` and Web UI setup must write config only; they must not build indexes, start services, call providers, or run research.

### Workspace

- The configured default workspace is the runtime root regardless of shell launch directory.
- The workspace must contain app-managed `tasks/`, `indexes/local/`, `reports/web/`, and `logs/`.
- Relative paths entered during initialization may be resolved against launch cwd before being saved as absolute paths.

### Local RAG

- Local RAG must use prebuilt indexes.
- Local RAG must accept only `ready` index status.
- If index status is `missing`, `stale`, `building`, or `failed`, Local RAG must fail before retrieval and instruct the user to run `research-agent kb rebuild`.
- Ingestion must read Markdown, plain text, PDF, and HTML sources.
- Markdown ingestion must parse frontmatter, title/headings, Markdown links, and wikilinks.
- Chunking must be heading-first for Markdown and paragraph-based for other extracted text.
- Local Result must include relevant content and source path, with optional heading path and offsets.
- Local RAG must not generate a Web Report File.

### Web Research Runtime

- Web Research must use LangGraph state graph and Blackboard Pattern.
- The graph must include Planner, ResearchExecutor, Supervisor, Plan Revision via Planner reuse, and Curator.
- There must be no separate Final Check node in V1.
- Context Builder must centralize role-specific context construction.
- Role inputs and outputs must use typed schemas.
- PlannerOutput must contain `research_title` and proposed subtask questions.
- Runtime must assign subtask IDs such as `st_1`, `st_2` and maintain subtask statuses.
- ResearchExecutor must execute Supervisor-selected subtasks and return one ExecutorOutput per subtask.
- ExecutorOutput must include `subtask_id`, `status`, `findings`, `sources`, and optional `failure_reason`.
- SupervisorOutput must include route decision, reason, next subtask IDs, optional skipped subtask IDs, optional plan revision request, research gaps, and saturation.
- CuratorOutput must include title, summary, findings, and sources.
- Curator must not invent findings or sources.

### Web Tools

- Web Research tools must be exposed through Tool Registry, Tool Gateway, and Tool Runner.
- Tool Gateway must validate tool existence, input schema, and workflow permission.
- Tool Gateway must not enforce max tool calls or budget validation in V1.
- V1 tools must include `web.search`, `web.fetch_extract`, and `web.download_pdf`.
- `web.search` must use Tavily through a Search Provider interface.
- HTML extraction must use `httpx` and `trafilatura`.
- PDF extraction must use `pypdf`.
- Tool-level transient failures must be retried by the gateway according to configured retry count.

### Web Report

- Web Research must write a Markdown report to `{default_workspace}/reports/web/{topic_slug}-{yyyy-mm-dd}.md`.
- Report filenames must preserve Chinese, lowercase English, replace whitespace with hyphens, remove Windows-illegal filename characters, truncate long slugs, and append collision suffixes.
- Web report must contain frontmatter, Summary, Findings, and Sources.
- Web report must not include workflow-internal research gaps.
- A Web task is `completed` only when CuratorOutput generation and report file writing both succeed.
- If report writing fails, the task must be `failed` with `file_write_error`.

### Task History

- Task history must record only finished tasks with status `completed` or `failed`.
- Task modes must be only `local` and `web`.
- CLI `both` must create separate Local and Web task records, not a parent task.
- SQLite tasks table must store `task_id`, `mode`, `status`, `title_or_question`, `created_at`, `completed_at`, optional `report_path`, and `result_path`.
- Progress events must be stored in task-local `events.jsonl`, not in SQLite.
- Result files must be stored as task-local `result.json`.
- Result files must not store full Web source text, raw tool results, prompts, model completions, executor scratchpads, or full progress events.

### Progress

- Progress records must be phase-based.
- Local phase must be `local_rag`.
- Web phases must be `web_planning`, `web_execution`, `web_supervision`, `web_revision`, and `web_curation`.
- Event type must be limited to `started`, `progress`, `completed`, and `failed`.
- Progress detail items must remain display-only and must not drive routing, curation, or recovery.

### Web UI

- Web UI must include Setup View, Research Page, Tasks Page, Knowledge Base Index Page, Local Result Page, and Web Report Page.
- Research Page must provide separate Local RAG and Web Research start areas.
- Web UI must not provide Run Both in V1.
- Tasks Page must list all finished Local and Web tasks in one mixed list sorted by `created_at` descending.
- Clicking a finished task row must navigate to the mode-appropriate result page.
- Web UI must use FastAPI + SSE for progress streaming.

### CLI

- CLI must provide `init`, `local`, `web`, `both`, `task list`, `kb status`, and `kb rebuild`.
- CLI must not provide generic `research`, `task show`, `task delete`, `kb update`, `kb clean`, `kb delete`, JSON output mode, deposit, or note-editing commands in V1.
- CLI must stream progress while a command is active.
- CLI must print `[code] message` for Research Errors.
- CLI must exit non-zero for failed tasks, busy conflicts, invalid setup, index failures, runtime failures, and report write failures.

## API Requirements

V1 Web API must expose:

- `GET /api/setup/status`
- `POST /api/setup/init`
- `POST /api/research/local`
- `POST /api/research/web`
- `GET /api/tasks/active`
- `GET /api/tasks/finished`
- `GET /api/tasks/{task_id}/events`
- `GET /api/tasks/{task_id}/result`
- `GET /api/kb/status`
- `POST /api/kb/rebuild`

The Web API must not expose Run Both, task deletion, note management, settings editing, or task-history detail endpoints beyond current result lookup.

## Data Requirements

### Task ID

`task_id` must use:

```text
task_yyyymmdd_hhmmss_<random6>
```

### Timestamps

Persisted timestamps must use UTC ISO 8601 with `Z`.

### Research Error

All user-facing errors must use:

```json
{
  "code": "...",
  "message": "..."
}
```

Required V1 codes include:

- `config_missing`
- `config_invalid`
- `busy`
- `kb_index_missing`
- `kb_index_stale`
- `kb_index_building`
- `kb_index_failed`
- `model_error`
- `search_error`
- `tool_error`
- `schema_validation_failed`
- `runtime_error`
- `file_write_error`

## Testing Seams

The highest-value testing seams are:

1. Core Service use cases: `init_config`, `run_local_research`, `run_web_research`, `run_both`, `list_finished_tasks`, `get_kb_status`, and `rebuild_kb_index`.
2. Local RAG ingestion and retrieval: parser, chunker, manifest/staleness detector, FTS/vector index writer, retrieval result builder.
3. Web Research Runtime: Planner schema handling, Executor tool loop, Supervisor routing, runtime route guard, Plan Revision append behavior, Curator output validation.
4. Tool Gateway: tool existence validation, input schema validation, workflow permission validation, transient retry behavior.
5. Report writer: filename generation, collision handling, Markdown rendering, and `file_write_error` failure semantics.
6. Task persistence: SQLite task rows, task folders, `events.jsonl`, `result.json`, and finished task listing.
7. Interface adapters: CLI output/exit codes and FastAPI endpoint behavior.
8. Web UI flows: setup, start Local, start Web, stream progress, view finished tasks, open Local Result Page, open Web Report Page.

## Acceptance Criteria

- `research-agent init` creates valid user config and workspace directories without scanning or indexing.
- `research-agent kb rebuild` builds Local RAG indexes from configured sources and reports file/chunk counts.
- `research-agent kb status` reports missing/ready/stale/building/failed with vault path and index metadata.
- `research-agent local "question"` returns top Local Results when index is ready.
- `research-agent local "question"` fails before retrieval when index is missing or stale.
- `research-agent web "question"` streams phase progress and produces a Markdown report when successful.
- A Web task with CuratorOutput success but report write failure is stored as `failed` with `file_write_error`.
- `research-agent both "question"` starts separate Local and Web tasks and exits non-zero if either fails.
- Web UI setup can create initial config.
- Web UI can run Local RAG and display Local Result Page.
- Web UI can run Web Research, stream progress, and display Web Report Page.
- Web UI Tasks Page lists finished Local and Web tasks together and can open result pages.
- No V1 flow modifies the user's Markdown Vault.
- Default tests run deterministically offline.

## Verification Requirements

Every implemented feature must satisfy the project agent rule in `AGENTS.md`: after implementation, it must pass subagent review, Claude Code review where available, unit tests, integration tests, and e2e tests before being considered complete.

V1 verification should include:

- Python unit tests with `uv run pytest`.
- Integration tests for Core Service, task persistence, Local RAG index lifecycle, and Web Research with fake adapters.
- Web tests with `npm test` once the Web UI exists.
- Playwright e2e tests for critical UI flows once the Web UI exists.
- Live provider/network tests only behind an explicit opt-in environment flag.

## Implementation Phases

1. Configuration, workspace, task storage, and CLI skeleton.
2. Knowledge Base status/rebuild and Local RAG CLI.
3. Web Research graph skeleton with fake model/tool adapters.
4. Real Web tools and LLM integration.
5. FastAPI and SSE progress stream.
6. React Web UI.

## Open Risks

- Local/Web isolation simplifies V1 but limits the value of `both`.
- Manual index rebuild may feel heavy when the vault changes frequently.
- Single global chat model may not fit Planner, Executor, Supervisor, and Curator equally well.
- Plan Revision is intentionally constrained and may be inefficient when the initial plan is poor.
- Prompt constants are easy to version but not user-customizable in V1.
- Coarse error codes may not always give enough user guidance.

## Deferred Upgrades

Deferred capabilities are tracked in `FUTURE_UPGRADES.md`. They include combined Local + Web research, local-aware planning/curation, automatic index refresh, richer evidence models, prompt overrides, role-specific model UI, task deletion, memory layer, browser automation, richer exports, and broader concurrency.
