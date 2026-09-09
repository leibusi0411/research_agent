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

1. **Local RAG** — hybrid retrieval (SQLite FTS5 + ChromaDB vectors with RRF fusion) over a user-approved Markdown vault, with optional LLM summarization (`local_summarizer` role).
2. **Web Research** — a LangGraph StateGraph multi-role pipeline (Planner → Executor → Supervisor → Curator) that searches via Tavily, fetches/extracts pages, and writes a Markdown report. Each role uses an OpenAI-compatible chat model.

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
    web/ (schemas, context, prompt_builders, role_invocation, executor, tools, graph, state_graph, provider_runtime, report)   ← Web Research runtime only
```

- **`core/`** — domain logic shared by all interfaces: config (TOML), KB indexing (FTS5+Chroma), local research retrieval, task storage (SQLite), workspace directories, chat/embedding model clients (OpenAI-compatible protocol).
- **`web/`** — Web Research runtime. `schemas.py` owns the blackboard state and role output dataclasses. `context.py`/`prompt_builders.py` build per-role context slices and prompts (code constants). `tools.py` is the ToolGateway (search/fetch/extract/PDF). `executor.py` runs the per-subtask tool loop; `graph.py`/`state_graph.py` are the LangGraph nodes and runner (SqliteSaver checkpoints). `report.py` renders the final Markdown report. `provider_runtime.py` is the real LLM-backed path (the default).
- **`api/`** — FastAPI app factory with SSE streaming for task progress events. API-only; does not serve `web/dist/`.
- **`cli.py`** — argparse CLI; uses the provider-backed runtime for `web`/`both` commands.

### Key patterns

- **Tests are offline and deterministic**: per-file `_FixedChatModelClient`/`_FixedEmbeddingClient` stubs, `RecordingEmbeddingClient`, and `FakeSearchProvider` replace real model/search calls; CLI tests run as subprocesses. Real-API tests (9) skip automatically when no user config is present.
- **Config**: TOML at `%APPDATA%/research_agent/config.toml` (or `~/.config/research_agent/config.toml`), overridable via `RESEARCH_AGENT_CONFIG_PATH`. Init with `research-agent init`.
- **Worktree-based dev**: main repo at `../research_agent`; this worktree is on branch `deepseek_dev`.
- **Domain glossary** in `CONTEXT.md` — read it before naming anything.
- **43 ADRs** in `docs/adr/` — decisions on stack, patterns, and boundaries. Numbered sequentially.
- **Deferred features** tracked in `TODO.md`.
- **中文优先**: 所有 review 生成的文件（代码审查报告、ADRs 审查等）一律用中文编写。中文翻译版作为主文件（不加 `-zh` 后缀），不保留英文原版。
- **Review 跟踪**: `REVIEW_TRACKER.md` 是项目唯一的审查与路线图文件（不含子目录中的独立 review 文档）。分三个部分：
  1. **项目阶段与当前状态** — 阶段级进度和当前策略，每次里程碑变化时更新
  2. **本轮 Review** — 最近一次审查的修复总结 + 按 P0/P1/P2/P3 分级的全部未解决问题（含编号、位置、一句话说明）。Code review 发现的新问题追加到对应优先级表中，已修复项移到"已完成修复"并标注日期
  3. **下一步建议** — 按推荐执行顺序排列的下一步工作任务，每次修复完成后更新
  维护规则：所有 review 发现统一用 R-xxx 编号（按发现顺序递增），修复用 F-xxx 编号。**禁止**创建 `docs/review/`、`REVIEW_R18.md` 等独立 review 文件——所有 review 内容必须合并到此文件。
  **每次修改代码 + code review 完成后，必须更新此文件**：已修复项标记 ✅ + 日期，新发现问题追加到对应优先级表，更新页头日期和测试计数。
- 配置文件已创建并配置，C:\Users\leibusi\AppData\Roaming\research_agent\config.toml   供测试使用

## 行为准则

> 以下原则偏向谨慎而非速度。对简单任务可灵活判断。

### 1. 编码前先思考

- 不确定时主动提问，不要猜测。
- 存在多种理解时列出选项，不要静默选择。
- 有更简单方案时主动提出，该拒绝时拒绝。

### 2. 简单优先

- 用最少代码解决问题，不做多余的事。
- 不添加未要求的功能、不为一次性代码创建抽象、不处理不可能发生的错误。
- 写完代码后审视：资深工程师会觉得过度设计吗？如果是，简化它。

### 3. 精准修改

- 只动必须动的代码。不"顺手优化"相邻代码、注释、格式。
- 匹配现有风格。不删除非本次改动导致的死代码（除非被要求）。
- 自己的改动产生的孤立 import/变量/函数必须清理。
- **检验标准**：每一处修改都应能追溯到用户的具体需求。

### 4. 目标驱动

- 把模糊任务转化为可验证目标：
  - "加校验" → 先写无效输入测试，再让测试通过
  - "修 bug" → 先写复现测试，再修复
  - "重构 X" → 确保重构前后测试均通过
- 多步骤任务先列简要计划，每步标注验证方式。
