# AGENTS.md

本文件供 AI 编码 agent 阅读，假设读者对本项目一无所知。

## 项目概览

**Research Agent** 是一个本地优先（local-first）的 AI 研究助手，提供两个**相互独立、不共享上下文**的工作流：

1. **Local RAG（本地知识库检索）** — 对用户指定的 Markdown vault 目录建立索引（SQLite FTS5 关键词 + ChromaDB 语义向量 + RRF 融合排序），检索后可选地用 LLM 生成自然语言总结（`local_summarizer` 角色）。索引构建是**只读**的，不修改源文件。支持 `.md`、`.txt`、`.pdf`、`.html`。
2. **Web Research（网络调研）** — 基于 LangGraph StateGraph 的多角色流水线：Planner → Executor → Supervisor → Curator。通过 ToolGateway 执行真实工具调用（Tavily 搜索、trafilatura 网页提取、pypdf PDF 解析），最终生成 Markdown 报告文件。

双界面：CLI（argparse，`research-agent` 命令）+ Web UI（React + Vite），两者通过统一的 FastAPI 后端和 CoreService 应用层暴露相同的能力面。

### 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| 包管理 | uv（Python 依赖与虚拟环境）；npm（前端） |
| 构建后端 | hatchling（src 布局，包在 `src/research_agent`） |
| API 框架 | FastAPI + uvicorn + sse-starlette（SSE 流式推送） |
| Agent 编排 | LangGraph + langgraph-checkpoint-sqlite（SqliteSaver checkpoint） |
| 存储 | SQLite（任务表 + FTS5 全文索引）、ChromaDB（向量索引） |
| HTTP 客户端 | httpx |
| 网页/PDF 提取 | trafilatura、pypdf |
| 搜索 API | Tavily |
| LLM 协议 | OpenAI-compatible（chat + embedding，推荐 DeepSeek） |
| 事件通道 | janus.Queue（同步/异步双面队列，EventStream） |
| 前端 | React 19 + Vite 6 + TypeScript + react-router-dom + lucide-react |
| 前端测试 | Vitest + Testing Library（单元）、Playwright（E2E，channel=chrome） |

## 项目结构

```
research_agent/
├── src/research_agent/
│   ├── __init__.py               # __version__
│   ├── cli.py                    # argparse CLI 入口（init/local/web/both/task list/task deposit/kb status/kb rebuild）
│   ├── api/
│   │   └── app.py                # FastAPI 工厂 create_app()，SSE 端点，服务 web/dist 静态文件
│   ├── core/                     # 领域逻辑（所有界面共享）
│   │   ├── config.py             # TOML 用户配置解析（全局 + per-role 模型覆盖）
│   │   ├── providers.py          # OpenAI 兼容 chat/embedding 客户端
│   │   ├── kb.py                 # 知识库索引（FTS5 + ChromaDB 混合）
│   │   ├── chroma_store.py       # ChromaDB 向量存储封装
│   │   ├── local_research.py     # Local RAG 检索（混合检索 + 可选 LLM 总结）
│   │   ├── deposit.py            # Knowledge Deposit：Web 报告显式沉淀进 vault（只增不改）
│   │   ├── service.py            # CoreService 应用层；one-active-task-per-family 任务锁
│   │   ├── tasks.py              # 任务历史存储（SQLite）
│   │   ├── workspace.py          # 工作区目录管理
│   │   ├── bus.py                # EventStream（janus.Queue，SSE/CLI 共用事件通道）
│   │   ├── errors.py             # 统一 ResearchError 错误对象（code + message）
│   │   └── ids.py                # ID 生成与校验（task_yyyymmdd_hhmmss_<random6> 等）
│   └── web/                      # Web Research 运行时（仅限 Web 调研，不含 Local RAG）
│       ├── schemas.py            # WebResearchState（blackboard）与各角色输出数据模型
│       ├── context.py            # Per-role 上下文切片构建（Context Builder）
│       ├── prompt_builders.py    # Per-role prompt 构建（提示词是代码常量）
│       ├── role_invocation.py    # LLM 角色调用 + 输出解析/修复
│       ├── executor.py           # ResearchExecutor（工具规划 → 执行 → 综合的循环）
│       ├── tools.py              # ToolGateway / ToolRunner / ToolRegistry / TavilySearchProvider
│       ├── state_graph.py        # StateGraphRunner（图运行器）
│       ├── graph.py              # LangGraph 节点函数与图构建
│       ├── provider_runtime.py   # Provider-backed 真实运行时
│       ├── fake_runtime.py       # 确定性 Fake Runtime（离线测试用）
│       └── report.py             # Markdown 报告生成
├── tests/                        # pytest，17 个测试文件，169 个测试（6 个 e2e 需真实 API key）
├── web/                          # React + Vite 前端
│   ├── src/
│   │   ├── App.tsx               # 主应用（Research / Tasks / KB / Setup 页面路由）
│   │   ├── api.ts                # API 客户端（类型 + 请求 + SSE 订阅）
│   │   ├── main.tsx              # React 入口
│   │   ├── components/           # ProcessView、ResultView、PhaseIndicator 等展示组件
│   │   ├── hooks/useSSE.ts       # SSE 订阅 hook
│   │   └── pages/                # ResearchPage / TasksPage / KbPage / SetupPage
│   ├── tests/                    # Vitest 单元测试（api/App/sse）+ e2e/（Playwright）
│   ├── dist/                     # 构建产物（生产模式由 FastAPI 直接服务）
│   ├── vite.config.ts            # 插件、/api 代理（→ 127.0.0.1:8001）、Vitest 配置
│   ├── playwright.config.ts      # E2E 配置（自动起 5174 端口的 dev server）
│   └── package.json
├── docs/
│   ├── adr/                      # 45 个架构决策记录（0001~0045，顺序编号）
│   └── agents/                   # agent 协作约定（issue tracker、triage labels、domain docs）
├── CONTEXT.md                    # 领域术语表（命名前必读）
├── TODO.md                       # v1 有意延期的功能清单
├── REVIEW_TRACKER.md             # 唯一的审查与路线图文件（见下方维护规则）
├── CLAUDE.md                     # Claude Code 项目指令（行为准则）
├── USAGE.md / README.md          # 使用文档（中文）
└── pyproject.toml
```

## 构建与运行命令

```bash
# 安装 Python 依赖（含 dev 依赖组：pytest、pytest-asyncio）
uv sync

# CLI（入口：research-agent = research_agent.cli:main）
uv run research-agent init              # 交互式初始化配置
uv run research-agent local "问题"       # Local RAG 检索
uv run research-agent web "问题"         # Web Research 调研
uv run research-agent both "问题"        # 同时启动两个独立任务
uv run research-agent task list         # 已完成任务列表
uv run research-agent task deposit <id> # 沉淀 Web 报告到知识库 vault
uv run research-agent kb status         # 知识库索引状态
uv run research-agent kb rebuild        # 重建知识库索引

# 生产模式：构建前端 + 启动后端（同一进程服务静态文件与 API，端口 8000）
cd web && npm install && npm run build && cd ..
uv run uvicorn research_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000

# 前端开发模式：一条命令同时启动后端 API(8001) + Vite(5173，/api 自动代理到 8001)
cd web && npm run dev:all
```

注意：`create_app` 是工厂函数，uvicorn 必须带 `--factory`。

## 测试

```bash
# Python：全部 169 个测试，默认离线且确定性（ADR-0042；6 个 e2e 需真实 API key，否则自动 skip）
uv run pytest                          # 全部
uv run pytest -x                       # 首次失败即停
uv run pytest -k "state_graph"         # 按关键字筛选
uv run pytest tests/test_web_state_graph.py  # 单文件

# 真实 API 的端到端测试（pytest.mark.e2e）：需要用户配置中有真实
# chat model 与 Tavily 的 API key，否则自动 skip
uv run pytest tests/test_web_e2e.py -v -s -m e2e

# 前端
cd web && npm run test                 # Vitest 单元测试（jsdom，排除 tests/e2e）
cd web && npm run test:e2e             # Playwright E2E（自动起 5174 端口 dev server）
```

**测试设计原则**（新增测试必须遵守）：

- **离线且确定性**：默认测试不依赖网络或真实 API key。
- 使用确定性 fake 实现：`FakeChatModelClient`（按序出队模拟 LLM 响应并记录 prompts）、`FakeWebResearchRuntime`（模拟完整 Web Research 流水线）、`RecordingEmbeddingClient` / `FixedEmbeddingClient`（固定向量）。
- CLI 测试以子进程方式运行。
- pytest 配置在 `pyproject.toml`：`testpaths = ["tests"]`，`pythonpath = [".", "src"]`。

目前没有配置 linter、formatter 或 type-checker。

## 开发约定与代码风格

- **中文优先**：Review 生成的文件（代码审查报告、ADR 审查等）一律用中文编写，中文翻译版作为主文件（不加 `-zh` 后缀），不保留英文原版。文档（README/USAGE）也是中文。
- **命名遵守术语表**：`CONTEXT.md` 定义了领域语言（Local RAG、Web Research、Blackboard、Tool Gateway 等）。命名领域概念时使用其中的术语，避免使用被明确否决的同义词（每个词条下有 `_Avoid_` 列表）。
- **ADR 冲突规则**：若改动与 `docs/adr/` 中已有决策冲突，必须显式提出冲突，而不是静默推翻决策。ADR 共 45 个，顺序编号。
- **类型注解**：方法签名使用显式类型参数，不用 `*args, **kwargs`；运行时抽象用 `WebResearchRuntime` Protocol 而非 `object`。
- **简单优先**：用最少代码解决问题，不做未要求的抽象或功能；精准修改，不顺手重构相邻代码；自己改动产生的孤立 import/变量/函数必须清理。
- **错误模型**：用户可见错误统一为 `ResearchError`（`code` + `message`），CLI 渲染为 `[code] message` 并以非零码退出。
- **Schema 修复**：角色 LLM 输出不合规时允许一次修复重试；修复失败则以 `schema_validation_failed` 终止工作流。
- **时间戳**：持久化时间一律 UTC ISO 8601 带 `Z` 后缀。
- **任务并发边界**：同一 family（local / web）同时只允许一个活跃任务，由 CoreService 强制。

### REVIEW_TRACKER.md 维护规则

`REVIEW_TRACKER.md` 是项目**唯一**的审查与路线图文件，分三部分：项目阶段与当前状态、本轮 Review（P0~P3 分级问题表）、下一步建议。

- 所有 review 发现用 `R-xxx` 编号（递增），修复用 `F-xxx` 编号。
- **禁止**创建 `docs/review/`、`REVIEW_R18.md` 等独立 review 文件——所有 review 内容合并到此文件。
- 每次修改代码 + code review 完成后必须更新：已修复项标 ✅ + 日期，新发现追加到对应优先级表，更新页头日期和测试计数。

### Agent 工作流程规则

- 每实现一个功能后，必须使用 subagent review，并通过单元测试、集成测试和 e2e 测试；全部通过才算该功能完成。
- Issue 与 PRD 跟踪在 GitHub Issues（`leibusi0411/research_agent`），用 `gh` CLI 操作，见 `docs/agents/issue-tracker.md`。
- Triage 标签使用五标签词汇：`needs-triage`、`needs-info`、`ready-for-agent`、`ready-for-human`、`wontfix`，见 `docs/agents/triage-labels.md`。
- 开始改动前先读：`CONTEXT.md`（术语）、相关 `docs/adr/`（决策）、`TODO.md`（v1 有意延期的功能，不要重复实现）。详见 `docs/agents/domain.md`。
- 开发在 worktree 上进行：主仓库在 `../research_agent`，本工作区在 `deepseek_dev` 分支。

## 配置与安全

- 用户配置为 TOML 文件：Windows `%APPDATA%/research_agent/config.toml`，Linux/macOS `~/.config/research_agent/config.toml`，可用环境变量 `RESEARCH_AGENT_CONFIG_PATH` 覆盖。
- 配置包含 **API keys**（chat model、embedding model、Tavily search）：**绝不提交到仓库**，不在日志、报告或测试中打印真实 key。测试用 fake key（如 `"test-key"`）。
- 支持 per-role 模型覆盖：`[chat_model.planner|executor|supervisor|curator|local_summarizer]`，未配置时回退到全局 `[chat_model]`。
- 本项目是单用户本地优先应用：Web UI 只绑定 localhost；Web Research 不包含认证浏览、浏览器自动化或反爬绕过；知识库索引对用户 vault 是只读的。
- 工作区目录（`default_workspace`）存放运行态：`tasks/<task_id>/`（result.json、events.jsonl、checkpoints.sqlite、artifacts/web_sources/）、`indexes/`、`reports/web/`、`logs/`。这些是用户数据，不属于仓库。

## API 面（最小化 FastAPI + SSE，ADR-0038）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/setup/status` | 配置状态 |
| POST | `/api/setup/init` | 初始化配置 |
| POST | `/api/research/local` | 启动 Local RAG 任务 |
| POST | `/api/research/web` | 启动 Web Research 任务 |
| GET | `/api/tasks/active` | 活跃任务 |
| GET | `/api/tasks/finished` | 已完成任务 |
| GET | `/api/tasks/{task_id}/events` | SSE 进度事件流 |
| GET | `/api/tasks/{task_id}/result` | 任务结果 |
| DELETE | `/api/tasks/{task_id}` | 删除任务 |
| POST | `/api/tasks/{task_id}/deposit` | 沉淀 Web 报告到知识库 vault |
| GET | `/api/kb/status` | 知识库索引状态 |
| POST | `/api/kb/rebuild` | 重建索引 |

SSE 事件为 phase-based（`web_planning` / `web_execution` / `web_supervision` / `web_revision` / `web_curation` / `local_rag`），`event_type` 限 `started | progress | completed | failed`，带单调递增 `seq` 用于去重；持久化层是 `events.jsonl`，传输层是 EventStream（janus.Queue，容量 1024）。
