# Research Agent

本地优先的 AI 研究助手，提供独立的 **Local RAG**（本地知识库检索）和 **Web Research**（网络调研）两大工作流。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-104%20passed-brightgreen.svg)](https://github.com/leibusi0411/research_agent)

---

## 目录

- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [工作流说明](#工作流说明)
  - [Local RAG（本地知识库检索）](#local-rag本地知识库检索)
  - [Web Research（网络调研）](#web-research网络调研)
- [API 接口](#api-接口)
- [配置说明](#配置说明)
- [开发指南](#开发指南)
  - [项目结构](#项目结构)
  - [技术栈](#技术栈)
  - [测试](#测试)
  - [开发约定](#开发约定)
- [ADR（架构决策记录）](#adr架构决策记录)
- [项目路线图](#项目路线图)
- [License](#license)

---

## 核心特性

### Local RAG（本地知识库检索）

- **关键词检索**：基于 SQLite FTS5 全文搜索引擎 + 向量索引（Chroma 兼容），无需 LLM 参与
- **只读导入**：从用户指定的 Markdown vault 目录构建索引，不修改源文件
- **多格式支持**：`.md`、`.txt`、`.pdf`、`.html`
- **段落分块**：智能按段落、标题层级分块，保持上下文连贯性

### Web Research（网络调研）

- **多角色流水线**：Planner → Executor → Supervisor → Curator，模拟人类研究员的工作流程
- **真实工具调用**：通过 ToolGateway 实际执行网络搜索（Tavily）、网页抓取提取（trafilatura）、PDF 下载解析（pypdf）
- **多步骤执行**：每个子任务先规划工具调用 → 执行工具 → 合成结论，而非依赖 LLM 凭空生成
- **迭代优化**：Supervisor 自动评估研究进度，支持补全计划、跳过已完成任务
- **产物持久化**：自动生成 Markdown 报告、blackboard 快照、web_sources 快照

### 通用特性

- **离线测试**：所有 104 个测试均离线运行，使用确定性 fake 实现，无需网络或 API key
- **双界面**：CLI（argparse）+ Web UI（React + Vite），通过统一 FastAPI 接入
- **任务锁**：同一 family（local/web）同时只允许一个活跃任务，防止资源冲突
- **SSE 流式推送**：实时推送任务进度事件，支持 10 分钟超时
- **TOML 配置**：支持全局和 per-role 模型配置，配置路径可环境变量覆盖

---

## 系统架构

```
┌──────────────────────────────────────────────────────┐
│                    CLI (cli.py)                       │
│                  Web UI (React/Vite)                  │
└──────────────┬───────────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────────┐
│               FastAPI (api/app.py)                    │
│         SSE streaming · REST endpoints                │
└──────────────┬───────────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────────┐
│            CoreService (core/service.py)              │
│         one-active-task-per-family lock               │
└──┬─────────┬──────────┬──────────┬───────────────────┘
   │         │          │          │
   ▼         ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌────────┐ ┌──────────────────────┐
│config│ │  kb  │ │ local  │ │     web/              │
│.py   │ │ .py  │ │_research│ │  schemas.py          │
│TOML  │ │FTS5+ │ │.py     │ │  context.py          │
│      │ │Chroma│ │Local   │ │  tools.py (Gateway)  │
│      │ │      │ │RAG     │ │  prompt_builders.py  │
├──────┤ ├──────┤ ├────────┤ │  state_graph.py      │
│tasks │ │worksp│ │        │ │  role_invocation.py  │
│.py   │ │ace.py│ │        │ │  provider_runtime.py │
│SQLite│ │dirs  │ │        │ │  fake_runtime.py     │
├──────┤ ├──────┤ │        │ │  report.py           │
│provi-│ │errors│ │        │ │                      │
│ders  │ │.py   │ │        │ └──────────────────────┘
│.py   │ │ids.py│ │        │
│OpenAI│ │      │ │        │
│compat│ │      │ │        │
└──────┘ └──────┘ └────────┘
```

### 各层职责

| 层级 | 路径 | 职责 |
|------|------|------|
| **CLI** | `cli.py` | argparse 命令行入口；默认使用 provider-backed runtime |
| **Web UI** | `web/` | React + Vite 前端，通过 API 交互 |
| **API** | `api/app.py` | FastAPI 工厂函数，SSE 流式推送任务进度，服务静态文件 |
| **Core** | `core/` | 领域逻辑：配置、知识库索引、本地检索、任务存储、工作区 |
| **Web Runtime** | `web/` | Web Research 运行时：状态图、工具网关、prompt 构建、报告生成 |

---

## 快速开始

### 环境要求

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)（推荐）或 pip
- Tavily API key（Web Research 功能需要）
- OpenAI 兼容的 LLM API endpoint（支持 chat + embedding）

### 安装

```bash
# 克隆仓库
git clone https://github.com/leibusi0411/research_agent.git
cd research_agent

# 安装依赖
uv sync
```

### 初始化配置

```bash
# 交互式初始化
uv run research-agent init
```

这会引导你配置：
- **default_workspace**：工作区目录（存放索引、任务结果）
- **knowledge_base_path**：Markdown vault 目录（Local RAG 的索引源）
- **chat_base_url / chat_api_key / chat_model**：LLM 模型配置
- **embedding_base_url / embedding_api_key / embedding_model**：Embedding 模型配置
- **search_api_key**：Tavily 搜索 API key

配置文件保存在：
- Windows: `%APPDATA%/research_agent/config.toml`
- Linux/macOS: `~/.config/research_agent/config.toml`

可通过环境变量 `RESEARCH_AGENT_CONFIG_PATH` 覆盖路径。

### 运行任务

```bash
# 本地知识库检索
uv run research-agent local "What is LangGraph?"

# 网络调研
uv run research-agent web "Latest developments in AI agents"

# 同时运行本地检索 + 网络调研
uv run research-agent both "AI agent frameworks comparison"
```

### 启动 Web UI

```bash
# 构建前端（首次需要）
cd web && npm install && npm run build && cd ..

# 启动 API 服务器（同时服务前端静态文件）
uv run uvicorn research_agent.api.app:create_app --factory --port 8000
```

浏览器打开 `http://localhost:8000` 即可使用 Web UI。

---

## 工作流说明

### Local RAG（本地知识库检索）

**流程**：扫描 vault 目录 → 解析文件 → 分段 → 构建 FTS5 + 向量索引 → 关键词查询

1. **索引构建**：运行 `research-agent init` 或调用 `POST /api/kb/rebuild`
2. **检索**：基于 FTS5 MATCH 语法进行关键词搜索，配合向量相似度排序，返回 top-10 结果
3. **无 LLM 参与**：Local RAG 仅做检索和呈现，不对内容进行总结或改写

**支持的格式**：
| 格式 | 说明 |
|------|------|
| `.md` | Markdown 文件，支持 frontmatter 解析、标题层级提取、wikilinks |
| `.txt` | 纯文本文件 |
| `.pdf` | PDF 文件，通过 pypdf 提取文本 |
| `.html` / `.htm` | HTML 文件，通过 trafilatura 提取正文 |

### Web Research（网络调研）

**流程**：Planner → Executor（含工具调用）→ Supervisor → Curator

```
                        ┌──────────────┐
                        │   Planner     │
                        │  制定调研计划   │
                        └──────┬───────┘
                               │ subtasks
                               ▼
                    ┌─────────────────────┐
                    │     Executor × N     │
                    │  多步骤工具调用流程    │
                    │                     │
                    │  1. Tool Plan       │ ← LLM 规划工具调用
                    │  2. Execute Tools   │ ← 实际调用搜索/抓取/提取
                    │  3. Synthesize      │ ← LLM 从结果中提炼结论
                    └──────────┬──────────┘
                               │ findings + sources
                               ▼
                    ┌──────────────────┐
                    │   Supervisor      │
                    │  评估进度/决策路由  │
                    └──┬────┬────┬─────┘
                       │    │    │
              continue  revise curate fail
                 │       │     │      │
                 │       ▼     │      ▼
                 │   Planner   │  终止（失败）
                 │  (修正计划)  │
                 └─────────────┘
                       │
                       ▼
              ┌────────────────┐
              │    Curator      │
              │  生成最终报告    │
              └────────────────┘
```

**关键设计决策**：

- **Executor 遵循 ADR-015/016**：通过 ToolGateway 执行真实工具调用，而非依赖 LLM 凭空生成数据
- **Supervisor 路由守卫**：超过 `max_retrieval_rounds` 时自动切换到 curate/fail，防止无限循环
- **产物持久化**：blackboard_snapshot.json（状态快照）、artifacts/web_sources/（源快照）

**可用工具**：
| 工具 | 说明 | 参数 |
|------|------|------|
| `web.search` | Tavily 网页搜索 | `query`, `max_results` |
| `web.fetch_extract` | 抓取网页并提取正文 | `url` |
| `web.download_pdf` | 下载 PDF 并提取文本 | `url` |

---

## API 接口

### 配置管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/setup/status` | 检查配置状态 |
| `POST` | `/api/setup/init` | 初始化配置 |

### 任务管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/research/local` | 启动 Local RAG 任务 |
| `POST` | `/api/research/web` | 启动 Web Research 任务 |
| `GET` | `/api/tasks/active` | 查询活跃任务 |
| `GET` | `/api/tasks/finished` | 查询已完成任务 |
| `GET` | `/api/tasks/{task_id}/events` | SSE 流获取任务进度事件 |
| `GET` | `/api/tasks/{task_id}/result` | 获取任务结果 |

### 知识库

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/kb/status` | 查询知识库索引状态 |
| `POST` | `/api/kb/rebuild` | 重建知识库索引 |

### SSE 事件类型

```json
{
  "task_id": "task_xxx",
  "mode": "web",
  "phase": "web_planning | web_execution | web_supervision | web_revision | web_curation",
  "event_type": "started | progress | completed | failed",
  "message": "Human-readable description",
  "details": { "items": [] }
}
```

---

## 配置说明

完整配置示例（`config.toml`）：

```toml
[workspace]
default_workspace = "C:\\Users\\xxx\\research_agent_data"
knowledge_base_path = "C:\\Users\\xxx\\vault"

[research]
max_retrieval_rounds = 3
max_concurrent_subtasks = 3

[chat_model]
provider = "openai_compatible"
base_url = "https://api.deepseek.com/v1"
api_key = "sk-xxx"
model = "deepseek-chat"

[chat_model.planner]
model = "deepseek-chat"  # 可选：为 Planner 指定不同模型

[embedding_model]
provider = "openai_compatible"
base_url = "https://api.deepseek.com/v1"
api_key = "sk-xxx"
model = "deepseek-embedding"

[search]
provider = "tavily"
api_key = "tvly-xxx"

[index]
backend = "sqlite_fts5_chroma"

[web_tools]
request_timeout_seconds = 45
pdf_timeout_seconds = 90
max_response_bytes = 20971520
max_pdf_bytes = 104857600
search_top_k = 10
search_top_k_max = 20
tool_retries = 2
```

### 角色级模型覆盖

在 `[chat_model.<role>]` 下可为每个角色指定不同的模型：

- `chat_model.planner` — Planner 角色
- `chat_model.executor` — Executor 角色
- `chat_model.supervisor` — Supervisor 角色
- `chat_model.curator` — Curator 角色

未指定时回退到全局 `[chat_model]` 配置。

---

## 开发指南

### 项目结构

```
research_agent/
├── src/research_agent/
│   ├── api/
│   │   └── app.py              # FastAPI 应用工厂
│   ├── cli.py                   # argparse CLI
│   ├── core/
│   │   ├── config.py            # TOML 配置解析
│   │   ├── errors.py            # 统一错误类型
│   │   ├── ids.py               # ID 生成与校验
│   │   ├── kb.py                # 知识库索引（FTS5 + 向量）
│   │   ├── local_research.py    # Local RAG 检索
│   │   ├── providers.py         # OpenAI 兼容模型客户端
│   │   ├── service.py           # CoreService（应用层）
│   │   ├── tasks.py             # 任务存储（SQLite）
│   │   └── workspace.py         # 工作区目录管理
│   └── web/
│       ├── context.py           # Per-role 上下文构建
│       ├── fake_runtime.py      # 确定性 Fake Runtime（测试/CLI）
│       ├── prompt_builders.py   # Per-role Prompt 构建
│       ├── provider_runtime.py  # Provider-backed Runtime
│       ├── report.py            # Markdown 报告生成
│       ├── role_invocation.py   # LLM 角色调用 + schema 修复
│       ├── schemas.py           # 数据模型与状态
│       ├── state_graph.py       # StateGraphRunner + ResearchExecutor
│       └── tools.py             # ToolGateway（搜索/抓取/提取）
├── tests/
│   ├── test_api_app.py
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_core_service.py
│   ├── test_kb.py
│   ├── test_local_research.py
│   ├── test_model_providers.py  # （含 1 个 web research 集成测试）
│   ├── test_service_run_both.py
│   ├── test_tasks.py
│   ├── test_web_context.py
│   ├── test_web_e2e.py          # 端到端集成测试（需真实 API key）
│   ├── test_web_e2e_simple.py   # 端到端简单测试
│   ├── test_web_fake_runtime.py
│   ├── test_web_prompt_builders.py
│   ├── test_web_report.py
│   ├── test_web_schemas.py
│   ├── test_web_state_graph.py
│   └── test_web_tools.py
├── web/                         # React + Vite 前端
│   ├── src/
│   ├── dist/                    # 构建产物（API 服务）
│   └── package.json
├── docs/
│   └── adr/                     # 43 个架构决策记录
├── CLAUDE.md                    # Claude Code 项目指令
├── CONTEXT.md                   # 领域术语表
├── REVIEW_TRACKER.md            # 审查与路线图
├── TODO.md                      # 延期功能跟踪
├── pyproject.toml
└── README.md
```

### 技术栈

| 组件 | 技术 |
|------|------|
| **语言** | Python 3.11+ |
| **包管理** | uv |
| **API 框架** | FastAPI |
| **前端** | React 18 + Vite |
| **数据库** | SQLite（FTS5 全文搜索 + 向量存储） |
| **HTTP 客户端** | httpx |
| **HTML 提取** | trafilatura |
| **PDF 提取** | pypdf |
| **搜索 API** | Tavily |
| **LLM 协议** | OpenAI-compatible |

### 测试

```bash
uv run pytest                          # 运行全部 104 个测试
uv run pytest -x                       # 首次失败即停止
uv run pytest -k "state_graph"         # 按关键字筛选
uv run pytest tests/test_web_state_graph.py  # 单个文件
```

**测试设计原则**：
- **离线与确定性**：所有测试不依赖网络或真实 API key
- `FakeChatModelClient`：模拟 LLM 响应（按序出队），记录所有 prompts
- `FakeWebResearchRuntime`：模拟完整 Web Research 流水线
- `RecordingEmbeddingClient`：记录 embedding 请求，返回固定向量
- `FixedEmbeddingClient`：返回确定性 embedding（用于 CLI 测试）

### 开发约定

- **中文优先**：Review 文件、ADR 审查等用中文编写
- **类型注解**：使用 `WebResearchRuntime` Protocol 而非 `object`
- **显式参数**：方法签名使用显式类型参数，不使用 `*args, **kwargs`
- **Schema 修复**：`invoke_role_json` 在 LLM 输出不合规时自动进行一次修复重试
- **REVIEW_TRACKER.md**：唯一的审查与路线图文件，问题修复后及时更新

---

## ADR（架构决策记录）

项目包含 **43 个 ADR**（`docs/adr/`），覆盖技术栈选择、架构模式、工程边界等关键决策。关键 ADR：

| ADR | 决策 | 实现状态 |
|-----|------|----------|
| 0001 | Python/FastAPI/React/SQLite 技术栈 | ✅ |
| 0003 | SQLite 任务存储 + 文件结果 | ✅ |
| 0004 | Context Builder + 类型化 Schema | ✅ |
| 0005 | LangGraph 检查点与 Task State 分离 | ✅ |
| 0007 | Tavily Search Provider | ✅ |
| 0013 | StateGraph + Blackboard 模式 | ✅ |
| 0015 | 工具网关（ToolGateway） | ✅ Executor 已集成 |
| 0016 | 单一 ResearchExecutor | ✅ 已实现工具调用 |
| 0026 | SQLite FTS5 + 向量索引 | ✅ |
| 0031 | 函数调用工具 + Registry/Gateway/Runner | ✅ |
| 0038 | 最小化 FastAPI + SSE 接口 | ✅ |
| 0042 | 确定性离线测试 | ✅ 104 passed |
| 0043 | uv (Python) + npm (Web UI) | ✅ |

完整 ADR 合规率：**~97%**（1 个 P2 问题待解决：tool call 记录持久化）

---

## 项目路线图

### 当前阶段：阶段 5 — 端到端验证 ✅ → 🔄

- ✅ 真实 LLM 集成测试（104 tests passed）
- ✅ Executor 工具调用集成
- ✅ 多步骤工具调用流程
- 🔄 性能优化
- 🔄 错误处理增强（网络超时、API 限流、工具调用失败回退）

### 下一步

| 优先级 | 目标 | 说明 |
|--------|------|------|
| P1 | 测试覆盖补充 | `_default_web_runtime` 单测、并发任务、SSE 超时 |
| P1 | 错误处理增强 | 工具调用失败回退机制、优雅降级 |
| P2 | 结构化产物持久化 | tool call 记录、model usage metadata |
| P2 | 工具调用数量上限 | 添加 `max_tool_calls_per_plan` 限制 |
| P3 | 文档修正 | Chroma 实现说明更新 |
| P3 | 死代码清理 | `build_executor_prompt`（保留供备用入口） |

详见 [`REVIEW_TRACKER.md`](REVIEW_TRACKER.md)。

---

## License

MIT License. 详见 [LICENSE](LICENSE) 文件。
