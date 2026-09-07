# Research Agent

本地优先的 AI 研究助手，提供独立的 **Local RAG**（本地知识库检索）和 **Web Research**（网络调研）两大工作流。

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-green.svg)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-18+-61DAFB.svg)](https://react.dev/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-67%20passed-brightgreen.svg)](https://github.com/leibusi0411/research_agent)

---

## 目录

- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [详细使用教程](#详细使用教程)
  - [1. 环境准备](#1-环境准备)
  - [2. 初始化配置](#2-初始化配置)
  - [3. CLI 命令行使用](#3-cli-命令行使用)
  - [4. Web UI 使用](#4-web-ui-使用)
  - [5. 前端开发模式](#5-前端开发模式)
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
- [常见问题](#常见问题)
- [ADR（架构决策记录）](#adr架构决策记录)
- [项目路线图](#项目路线图)
- [License](#license)

---

## 核心特性

### Local RAG（本地知识库检索）

- **混合检索**：SQLite FTS5 关键词 + ChromaDB 语义向量 + RRF 融合排序，检索精读
- **LLM 总结**：检索后用 LLM 对匹配块进行综合总结生成自然语言答案（可选，config 中配置 `local_summarizer` 角色模型）
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

- **离线测试**：所有 67 个测试均离线运行，使用确定性 fake 实现，无需网络或 API key
- **双界面**：CLI（argparse）+ Web UI（React + Vite），通过统一 FastAPI 接入
- **任务锁**：同一 family（local/web）同时只允许一个活跃任务，防止资源冲突
- **SSE 流式推送**：实时推送任务进度事件，支持 30 分钟超时
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
- Node.js 18+（仅 Web UI 需要）
- Tavily API key（[获取地址](https://tavily.com/)，Web Research 功能需要）
- OpenAI 兼容的 LLM API endpoint（支持 chat + embedding，推荐 [DeepSeek](https://platform.deepseek.com/)）

### 安装

```bash
# 克隆仓库
git clone https://github.com/leibusi0411/research_agent.git
cd research_agent

# 安装 Python 依赖
uv sync

# 安装前端依赖（仅使用 Web UI 时需要）
cd web && npm install && cd ..
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

---

## 详细使用教程

### 1. 环境准备

#### 获取 API Keys

Research Agent 需要两个外部 API 才能发挥全部功能：

| API | 用途 | 获取地址 | 是否必需 |
|-----|------|----------|----------|
| **LLM API** (OpenAI 兼容) | 驱动 Web Research 的 Planner/Executor/Supervisor/Curator | [DeepSeek](https://platform.deepseek.com/)、[OpenAI](https://platform.openai.com/) 等 | Web Research 必需 |
| **Embedding API** (OpenAI 兼容) | 为 Local RAG 生成向量嵌入 | 同上 | Local RAG 必需 |
| **Tavily Search API** | Web Research 的网络搜索工具 | [tavily.com](https://tavily.com/) | Web Research 必需 |

> **推荐配置**：使用 DeepSeek 的 chat + embedding API（性价比高），配合 Tavily 免费额度即可跑通全部功能。

#### 准备知识库目录（可选，仅 Local RAG 需要）

创建一个 Markdown vault 目录，放入你的 `.md`、`.txt`、`.pdf`、`.html` 文件：

```bash
mkdir ~/my_knowledge_vault
# 将你的笔记、文档、PDF 等放入此目录
```

### 2. 初始化配置

有三种方式完成初始化配置：

#### 方式 A：CLI 交互式初始化（推荐）

```bash
uv run research-agent init
```

按提示依次输入各项配置。已有配置文件时会显示当前值，直接回车保留不变。

#### 方式 B：通过 Web UI 初始化

启动服务器后（见下方），浏览器打开 `http://localhost:8000`，如果未配置会自动跳转到 Setup 页面，填写表单提交即可。

#### 方式 C：手动创建配置文件

在配置路径创建 `config.toml`（完整示例见[配置说明](#配置说明)）。

### 3. CLI 命令行使用

#### 基本命令

```bash
# 查看帮助
uv run research-agent --help

# 查看版本
uv run research-agent --version
```

#### 本地知识库检索（Local RAG）

从你的 Markdown vault 中检索信息，并用 LLM 生成总结：

```bash
# 基础检索（自动输出 LLM 总结 + 原始来源）
uv run research-agent local "Agent 三大范式分别是什么"

# 中文检索
uv run research-agent local "什么是 RAG 系统？"

# 检索多个关键词（FTS5 MATCH 语法）
uv run research-agent local "machine learning OR deep learning"
```

输出包含：
- **Summary**：LLM 基于检索结果生成的综合答案（带引用编号）
- **Sources**：匹配的文本片段、来源文件路径、标题路径

#### 网络调研（Web Research）

启动多角色流水线进行网络调研：

```bash
# 基础调研
uv run research-agent web "Latest developments in AI agents 2025"

# 深度调研（自动搜索、抓取、分析、合成报告）
uv run research-agent web "Compare LangGraph, CrewAI, and AutoGen frameworks"

# 技术调研
uv run research-agent web "Best practices for RAG systems in production"
```

Web Research 执行流程：
0. **Prior Knowledge**（默认开启）：启动前先在本地知识库检索一次，Planner 据此避开本地已覆盖的内容（可用 `inject_local_context = false` 关闭）
1. **Planner** 分析问题，制定调研计划（拆分为若干子任务）
2. **Executor** 逐个执行子任务：规划工具调用 → 搜索/抓取 → 合成发现
3. **Supervisor** 评估进度，决定继续/修订/完成
4. **Curator** 整合所有发现，生成最终 Markdown 报告

执行完成后，报告文件保存在工作区的 `reports/web/` 下，任务结果与中间产物在 `tasks/<task_id>/` 下。

#### 沉淀报告到知识库（Knowledge Deposit）

把已完成的 Web Research 报告显式保存进知识库 vault，让后续 Local RAG 检索能命中：

```bash
uv run research-agent task deposit <task_id>

# 之后重建索引即可检索到
uv run research-agent kb rebuild
```

报告会复制到 vault 的 `web-research/` 子目录（只新增笔记，不修改已有内容；同一任务重复沉淀会提示 `already_deposited`）。详见 [USAGE.md](USAGE.md)。

Web UI 中，已完成的 Web Report 页面（Research 页或 Tasks 页打开的报告视图）提供 **Deposit to Knowledge Base** 按钮，沉淀成功后可直接点 **Rebuild Index** 重建索引。

#### 同时运行两种检索

```bash
uv run research-agent both "AI agent frameworks comparison"
```

这将并行启动 Local RAG 和 Web Research，同时获得本地知识和网络信息。

#### 查看结果

CLI 会在终端直接输出结果。完整的 Markdown 报告保存在：
```
<workspace>/tasks/<task_id>/report.md       # Web Research 报告
<workspace>/tasks/<task_id>/result.json     # 结构化结果
<workspace>/tasks/<task_id>/events.jsonl    # 进度事件日志
```

### 4. Web UI 使用

Web UI 提供可视化的研究界面，支持任务管理、实时进度查看和结果浏览。

#### 构建并启动（生产模式）

```bash
# 步骤 1：构建前端（首次或前端代码变更后需要）
cd web
npm run build
cd ..

# 步骤 2：启动后端服务器（同时服务前端静态文件 + API）
uv run uvicorn research_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

浏览器打开 **http://localhost:8000** 即可使用。

> **说明**：`--factory` 参数表示 `create_app` 是一个工厂函数（返回 FastAPI 实例），而非直接是 FastAPI 实例。

Web UI 有三个页面：

| 页面 | 功能 |
|------|------|
| **Research** | 主界面 — 输入问题，启动 Local RAG 或 Web Research，实时查看进度和结果 |
| **Tasks** | 查看历史任务列表，点击可查看详情（结果 + 进度事件） |
| **Knowledge Base** | 查看知识库索引状态，重建索引 |

#### 首次使用 Web UI

如果尚未配置，打开浏览器后会自动跳转到 Setup 页面。填写以下信息：

| 字段 | 说明 | 示例 |
|------|------|------|
| `default_workspace` | 工作区目录 | `C:\Users\xxx\research_data` |
| `knowledge_base_path` | 知识库 vault 目录 | `C:\Users\xxx\vault` |
| `chat_base_url` | LLM API 地址 | `https://api.deepseek.com/v1` |
| `chat_api_key` | LLM API Key | `sk-xxx` |
| `chat_model` | 模型名称 | `deepseek-chat` |
| `embedding_base_url` | Embedding API 地址 | `https://api.deepseek.com/v1` |
| `embedding_api_key` | Embedding API Key | `sk-xxx` |
| `embedding_model` | Embedding 模型名称 | `deepseek-embedding` |
| `search_api_key` | Tavily Search API Key | `tvly-xxx` |

提交后自动保存配置并跳转到 Research 页面。

### 5. 前端开发模式

如果你需要修改前端代码并进行实时测试，使用 Vite 开发服务器：

#### 启动方式

**推荐：一条命令启动前后端**

```bash
cd web
npm install        # 首次安装依赖（含 concurrently）
npm run dev:all    # 同时启动后端 API (8001) + 前端 Vite (5173)
```

浏览器打开 **http://localhost:5173** 即可进行前端开发和测试。

`concurrently` 会用一个终端同时运行两个服务，`-n api,web` 给每个进程加了前缀标签方便区分日志来源。

**备选：两个终端分别启动**（不想装 concurrently 时使用）

| 终端 | 命令 |
|------|------|
| 终端 1（后端） | `uv run uvicorn research_agent.api.app:create_app --factory --host 127.0.0.1 --port 8001` |
| 终端 2（前端） | `cd web && npm run dev` |

#### 开发模式说明

| 特性 | 说明 |
|------|------|
| **一键启动** | `npm run dev:all` 通过 concurrently 同时启动前后端 |
| **热更新 (HMR)** | 修改 `web/src/` 下的代码，浏览器自动刷新，无需手动构建 |
| **API 代理** | Vite 自动将 `/api/*` 请求代理到后端 `http://127.0.0.1:8001` |
| **端口** | 前端 `5173`，后端 `8001`（与生产模式的 `8000` 不同，避免冲突） |

#### 前端项目结构

```
web/
├── src/
│   ├── App.tsx          # 主应用组件（Research / Tasks / KB 三页面）
│   ├── api.ts           # API 客户端（类型定义 + 请求函数 + SSE 订阅）
│   └── main.tsx         # React 入口
├── tests/
│   └── setup.ts         # Vitest 测试配置
├── dist/                # 构建产物（npm run build 生成，API 自动服务）
├── index.html           # HTML 入口
├── vite.config.ts       # Vite 配置（插件、代理、测试）
├── tsconfig.json        # TypeScript 配置
└── package.json         # npm 依赖与脚本
```

#### 可用的前端脚本

```bash
cd web

npm run dev           # 启动 Vite 开发服务器（端口 5173，热更新）
npm run build         # TypeScript 检查 + Vite 生产构建 → dist/
npm run test          # 运行 Vitest 单元测试
npm run test:e2e      # 运行 Playwright E2E 测试
```

#### 前端测试

```bash
# 单元测试（Vitest）
cd web && npm run test

# E2E 测试（Playwright，需要先启动后端服务）
cd web && npm run test:e2e
```

---

## 工作流说明

### Local RAG（本地知识库检索）

**流程**：扫描 vault 目录 → 解析文件 → 分段 → 构建 FTS5 + ChromaDB 向量索引 → 混合检索（FTS5 + 语义 + RRF） → LLM 总结

1. **索引构建**：运行 `research-agent kb rebuild` 或调用 `POST /api/kb/rebuild`
2. **混合检索**：FTS5 关键词 + ChromaDB 语义向量 + RRF 融合排序，返回 top-10 结果
3. **LLM 总结**：将检索结果作为参考材料注入 prompt，调用 `local_summarizer` 角色模型生成综合答案（无 chat_model 时回退到纯检索模式）

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

- `chat_model.planner` — Web Research Planner 角色
- `chat_model.executor` — Web Research Executor 角色
- `chat_model.supervisor` — Web Research Supervisor 角色
- `chat_model.curator` — Web Research Curator 角色
- `chat_model.local_summarizer` — Local RAG 总结角色

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
│       ├── executor.py          # ResearchExecutor（工具规划/执行/综合）
│       ├── fake_runtime.py      # 确定性 Fake Runtime（测试/CLI）
│       ├── graph.py             # LangGraph 节点函数 + 图构建
│       ├── prompt_builders.py   # Per-role Prompt 构建
│       ├── provider_runtime.py  # Provider-backed Runtime
│       ├── report.py            # Markdown 报告生成
│       ├── role_invocation.py   # LLM 角色调用 + schema 修复
│       ├── schemas.py           # 数据模型与状态
│       ├── state_graph.py       # StateGraphRunner
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
│   │   ├── App.tsx              # 主组件
│   │   ├── api.ts               # API 客户端 + 类型
│   │   └── main.tsx             # 入口
│   ├── tests/
│   │   └── setup.ts
│   ├── dist/                    # 构建产物（API 服务）
│   ├── index.html
│   ├── vite.config.ts
│   ├── tsconfig.json
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
| **前端** | React 18 + Vite + TypeScript |
| **数据库** | SQLite（FTS5 全文搜索 + 向量存储） |
| **HTTP 客户端** | httpx |
| **HTML 提取** | trafilatura |
| **PDF 提取** | pypdf |
| **搜索 API** | Tavily |
| **LLM 协议** | OpenAI-compatible |

### 测试

```bash
uv run pytest                          # 运行全部测试（67 个，离线确定）
uv run pytest -x                       # 首次失败即停止
uv run pytest -k "state_graph"         # 按关键字筛选
uv run pytest tests/test_web_state_graph.py  # 单个文件

# 前端测试
cd web && npm run test                 # Vitest 单元测试
cd web && npm run test:e2e             # Playwright E2E 测试
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

## 常见问题

### 配置相关

**Q: 配置文件在哪里？**
- Windows: `%APPDATA%/research_agent/config.toml`
- Linux/macOS: `~/.config/research_agent/config.toml`
- 可通过环境变量 `RESEARCH_AGENT_CONFIG_PATH` 自定义路径

**Q: 如何更换 LLM 提供商？**
修改 `config.toml` 中 `[chat_model]` 和 `[embedding_model]` 的 `base_url`、`api_key`、`model`。任何 OpenAI 兼容的 API 均可使用（如 Ollama、vLLM、DeepSeek、OpenAI 等）。

**Q: 如何查看当前配置？**
```bash
# CLI 初始化时会显示当前值
uv run research-agent init

# 或直接查看配置文件
cat ~/.config/research_agent/config.toml  # Linux/macOS
type %APPDATA%\research_agent\config.toml  # Windows
```

### 前端相关

**Q: 前端启动后页面空白？**
1. 确认后端服务器已启动且端口正确（开发模式 8001，生产模式 8000）
2. 检查浏览器控制台是否有报错（F12 → Console）
3. 确认 `npm install` 已执行且无报错

**Q: 前端热更新不生效？**
1. 确认使用的是 `npm run dev` 而非 `npm run build` 的产物
2. 尝试刷新浏览器（Ctrl+Shift+R 强制刷新）
3. 重启 Vite 开发服务器

**Q: API 请求报 404？**
1. 确认后端服务器正在运行
2. 开发模式检查 `vite.config.ts` 中 proxy 配置是否指向正确的后端端口
3. 生产模式确认 `web/dist/` 已构建（`npm run build`）

### 运行相关

**Q: Web Research 执行时间很长？**
Web Research 涉及多轮 LLM 调用 + 网络搜索/抓取，通常需要 2-10 分钟。复杂话题可能需要更长时间。进度可通过 SSE 事件实时查看。

**Q: Local RAG 检索不到内容？**
1. 确认知识库已索引：`curl http://localhost:8000/api/kb/status` 检查 `file_count > 0`
2. 如未索引，运行 `uv run research-agent init` 或调用 `POST /api/kb/rebuild`
3. 尝试更具体的关键词或使用自然语言描述（支持 FTS5 关键词 + ChromaDB 语义混合检索）

**Q: 如何清理旧任务数据？**
```bash
# 删除工作区目录下的任务文件夹
rm -rf <workspace>/tasks/task_<old_task_id>/
```

---

## ADR（架构决策记录）

项目包含 **44 个 ADR**（`docs/adr/`），覆盖技术栈选择、架构模式、工程边界等关键决策。关键 ADR：

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
| 0044 | Local RAG LLM 总结（Augmentation + Generation） | ✅ |

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
