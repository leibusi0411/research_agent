# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                          # install dependencies
uv run pytest                    # run all tests (offline/deterministic by design)
uv run pytest tests/test_foo.py  # single test file
uv run pytest -k keyword         # filter tests by keyword
uv run research-agent <command>  # run CLI
```

There is no linter, formatter, or type-checker configured yet.

## Architecture

**Research Agent** is a local-first research tool with **two independent workflows** that never share context:

1. **Local RAG** — keyword retrieval over a user-approved Markdown vault using SQLite FTS5 + Chroma vector indexes. No LLM summarization.
2. **Web Research** — a LangGraph-like multi-role pipeline (Planner → Executor → Supervisor → Curator) that searches via Tavily, fetches/extracts pages, and writes a Markdown report. Each role uses an OpenAI-compatible chat model.

### Layers

```
CLI (cli.py)              Web UI (React/Vite, web/)
        \                   /
         \                 /
        FastAPI (api/app.py)          ← API layer
                |
          CoreService (core/service.py)  ← shared application layer; enforces one-active-task-per-family lock
         /        |        \        \
   config.py   kb.py     local_research.py  tasks.py  workspace.py  providers.py  errors.py  ids.py
         \
    web/ (schemas, context, tools, fake_runtime, provider_runtime, report)   ← Web Research runtime only
```

- **`core/`** — domain logic shared by all interfaces: config (TOML), KB indexing (FTS5+Chroma), local research retrieval, task storage (SQLite), workspace directories, chat/embedding model clients (OpenAI-compatible protocol).
- **`web/`** — Web Research runtime. `schemas.py` owns `WebResearchState` (the blackboard) and all role output dataclasses. `context.py` builds per-role prompts. `tools.py` is the ToolGateway (search/fetch/extract). `report.py` renders the final Markdown report. `fake_runtime.py` provides a deterministic fake for CLI and tests; `provider_runtime.py` is the real LLM-backed path (incomplete).
- **`api/`** — FastAPI app factory with SSE streaming for task progress events. Serves pre-built `web/dist/` static files.
- **`cli.py`** — argparse CLI; uses `FakeWebResearchRuntime` for `web`/`both` commands.

### Key patterns

- **Tests are offline and deterministic**: `FakeWebResearchRuntime` simulates the full Web Research pipeline; `FixedEmbeddingClient` replaces real embeddings. CLI tests run as subprocesses.
- **Config**: TOML at `%APPDATA%/research_agent/config.toml` (or `~/.config/research_agent/config.toml`), overridable via `RESEARCH_AGENT_CONFIG_PATH`. Init with `research-agent init`.
- **Worktree-based dev**: main repo at `../research_agent`; this worktree is on branch `deepseek_dev`.
- **Domain glossary** in `CONTEXT.md` — read it before naming anything.
- **43 ADRs** in `docs/adr/` — decisions on stack, patterns, and boundaries. Numbered sequentially.
- **Deferred features** tracked in `TODO.md`.
- **中文优先**: 所有 review 生成的文件（代码审查报告、ADRs 审查等）一律用中文编写。中文翻译版作为主文件（不加 `-zh` 后缀），不保留英文原版。
- **Review 跟踪**: `REVIEW_TRACKER.md` 是唯一的审查与路线图文件。每次 code review 后将新发现的问题追加到"待修复问题"；每完成一个修复后将其移到"已完成修复"并更新日期。阶段 4 实现进度也在此文件中维护。
- 配置文件已创建并配置，C:\Users\leibusi\AppData\Roaming\research_agent\config.toml   供测试使用
