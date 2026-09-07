# Research Agent 使用指南

## 目录

- [1. 环境准备](#1-环境准备)
- [2. 初始化配置](#2-初始化配置)
- [3. 配置文件说明](#3-配置文件说明)
- [4. CLI 命令行使用](#4-cli-命令行使用)
- [5. Web UI 使用](#5-web-ui-使用)
- [6. 开发模式](#6-开发模式)
- [7. 常见问题](#7-常见问题)

---

## 1. 环境准备

### 安装依赖

```bash
cd G:\VSCode_project\research_agent_deepseek

# Python 依赖
uv sync

# 前端依赖（仅使用 Web UI 时需要）
cd web && npm install && cd ..
```

### 获取 API Keys

| API | 用途 | 获取地址 |
|-----|------|----------|
| LLM API (OpenAI 兼容) | Web Research 流水线 + Local RAG 总结 | [DeepSeek](https://platform.deepseek.com/)、[SiliconFlow](https://siliconflow.cn/) |
| Embedding API (OpenAI 兼容) | 知识库向量索引 | 同上 |
| Tavily Search API | Web Research 网络搜索 | [tavily.com](https://tavily.com/) |

### 准备知识库目录（可选，仅 Local RAG 需要）

创建一个目录放入 `.md`、`.txt`、`.pdf`、`.html` 文件。推荐用 Obsidian vault 或任意 Markdown 文件夹。

---

## 2. 初始化配置

### 方式 A：CLI 命令行

```bash
uv run research-agent init \
  --default-workspace "C:\\Users\\xxx\\research_agent_data" \
  --knowledge-base-path "F:\\MyVault" \
  --chat-base-url "https://api.deepseek.com" \
  --chat-api-key "sk-xxx" \
  --chat-model "deepseek-chat" \
  --embedding-base-url "https://api.siliconflow.cn/v1" \
  --embedding-api-key "sk-xxx" \
  --embedding-model "Qwen/Qwen3-VL-Embedding-8B" \
  --search-api-key "tvly-xxx"
```

### 方式 B：Web UI

启动后浏览器访问，未配置时会自动跳转到 Setup 页面。

### 方式 C：手动创建配置文件

配置文件路径：
- **Windows**: `%APPDATA%\research_agent\config.toml`
- **Linux/macOS**: `~/.config/research_agent/config.toml`

可用环境变量 `RESEARCH_AGENT_CONFIG_PATH` 覆盖路径。

---

## 3. 配置文件说明

完整 `config.toml` 示例：

```toml
[workspace]
# 工作区目录（存放索引、任务结果）
default_workspace = "C:\\Users\\xxx\\research_agent_data"
# 知识库 vault 目录（Local RAG 的索引源）
knowledge_base_path = "F:\\MyVault"

[research]
# Web Research 最大检索轮次
max_retrieval_rounds = 3
# Web Research 最大并发子任务数
max_concurrent_subtasks = 3

[chat_model]
# 全局默认 chat 模型（所有角色回退到此配置）
provider = "openai_compatible"
base_url = "https://api.deepseek.com"
api_key = "sk-xxx"
model = "deepseek-chat"

# 以下为可选的角色级模型覆盖，未配置时回退到 [chat_model]
[chat_model.planner]
# model = "different-model"

[chat_model.executor]
# model = "different-model"

[chat_model.supervisor]
# model = "different-model"

[chat_model.curator]
# model = "different-model"

[chat_model.local_summarizer]
# Local RAG 总结专用模型（可选）

[embedding_model]
provider = "openai_compatible"
base_url = "https://api.siliconflow.cn/v1"
api_key = "sk-xxx"
model = "Qwen/Qwen3-VL-Embedding-8B"

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

### 角色模型说明

| 配置键 | 用途 | 默认 |
|--------|------|------|
| `chat_model` | 全局默认模型 | 必需 |
| `chat_model.planner` | Web Research 计划制定 | 回退到 chat_model |
| `chat_model.executor` | Web Research 子任务执行 | 回退到 chat_model |
| `chat_model.supervisor` | Web Research 进度监督 | 回退到 chat_model |
| `chat_model.curator` | Web Research 报告生成 | 回退到 chat_model |
| `chat_model.local_summarizer` | Local RAG 总结 | 回退到 chat_model |

---

## 4. CLI 命令行使用

### 查看帮助

```bash
uv run research-agent --help
```

### 本地知识库检索（Local RAG）

从知识库 vault 中检索信息，并用 LLM 生成总结：

```bash
# 基础用法
uv run research-agent local "你的问题"

# 示例
uv run research-agent local "Agent 三大范式分别是什么"
uv run research-agent local "什么是 RAG 系统"
```

输出格式：

```
Summary
根据参考资料，LLM Agent 的三种基础推理范式是：
1. ReAct — 推理与行动交替 [2]
2. Plan-and-Solve — 先计划再执行 [1]
3. Reflection — 执行后自我检查并修正 [1]
...

Sources
1. [chunk 文本内容]
   source_path: F:\MyVault\Agent\Agent Fundamentals.md
   heading_path: Agent 三大范式
2. ...
```

工作流程：

```
用户问题 → FTS5关键词 + ChromaDB语义检索 → RRF融合排序 → LLM总结 → 输出
```

### 网络调研（Web Research）

启动多角色流水线进行网络调研：

```bash
# 基础用法
uv run research-agent web "你的问题"

# 示例
uv run research-agent web "Latest developments in AI agents 2026"
uv run research-agent web "Compare LangGraph, CrewAI, and AutoGen"
```

执行流程：

```
Planner → Executor → Supervisor → Curator
  ↓         ↓           ↓           ↓
制定计划   搜索/抓取   评估进度    生成报告
```

产物保存路径：`<workspace>/tasks/<task_id>/`

| 文件 | 说明 |
|------|------|
| `result.json` | 结构化结果 |
| `events.jsonl` | 进度事件日志 |
| `report.md` | 最终 Markdown 报告 |
| `execution_trace.md` | 执行追踪（含 Mermaid 流程图） |

### 同时运行本地和网络检索

```bash
uv run research-agent both "你的问题"
```

并行启动 Local RAG 和 Web Research，各自独立执行，互不干扰。

### 知识库索引管理

```bash
# 查看索引状态
uv run research-agent kb status

# 输出示例
# status: ready
# vault_path: F:\MyVault
# file_count: 94
# chunk_count: 2788
# last_indexed_at: 2026-07-03T12:00:00Z

# 重建索引
uv run research-agent kb rebuild
```

索引状态说明：

| 状态 | 含义 | Local RAG 可用？ |
|------|------|:---:|
| `ready` | FTS5 + ChromaDB 均正常 | ✅ |
| `stale` | FTS5 可用，ChromaDB 过期或失败 | ✅ (降级为关键词) |
| `missing` | 从未构建过索引 | ❌ |
| `building` | 正在构建中 | ❌ |
| `failed` | 构建失败且无可用索引 | ❌ |

### 查看任务历史

```bash
uv run research-agent task list

# 输出示例
# task_id                          mode    status      title_or_question          created_at
# task_20260703_120000_abc123      local   completed   什么是RAG系统              2026-07-03T12:00:00Z
# task_20260703_120500_def456      web     completed   Latest AI news            2026-07-03T12:05:00Z
```

### 沉淀 Web 报告到知识库

```bash
uv run research-agent task deposit task_20260703_120500_def456

# 输出示例
# Deposited: F:\MyVault\web-research\latest-ai-news-2026-07-03.md
# Run research-agent kb rebuild to index the deposited report.
```

将已完成 Web Research 任务的报告文件复制到知识库 vault 的 `web-research/` 子目录（只新增笔记，不修改已有内容）。同一任务重复沉淀会报 `already_deposited`。沉淀后运行 `uv run research-agent kb rebuild` 重建索引，新笔记即可被 Local RAG 检索到。

Web UI 中也有相同能力：在已完成的 Web Report 视图（Research 页或 Tasks 页打开）点击 **Deposit to Knowledge Base**，成功后可继续点击 **Rebuild Index** 一键重建索引。

---

## 5. Web UI 使用

### 启动 Web 应用

```bash
# 进入 web 目录
cd G:\VSCode_project\research_agent_deepseek\web

# 一键启动前后端（推荐）
npm run dev:all
```

浏览器访问 **http://127.0.0.1:5173**

首次使用会自动跳转到 Setup 配置页面。配置完成后可访问三个页面：

| 页面 | 路由 | 功能 |
|------|------|------|
| **Research** | `/` | 输入问题，启动 Local RAG 或 Web Research，实时查看进度和结果 |
| **Tasks** | `/tasks` | 查看历史任务列表，点击查看详情 |
| **Knowledge Base** | `/kb` | 查看索引状态，一键重建索引 |

### 生产模式部署

```bash
# 1. 构建前端
cd web && npm run build && cd ..

# 2. 启动后端（自动服务前端静态文件 + API）
uv run uvicorn research_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

浏览器访问 **http://127.0.0.1:8000**

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/setup/status` | 检查配置状态 |
| `POST` | `/api/setup/init` | 初始化配置 |
| `POST` | `/api/research/local` | 启动 Local RAG |
| `POST` | `/api/research/web` | 启动 Web Research |
| `GET` | `/api/tasks/active` | 查询活跃任务 |
| `GET` | `/api/tasks/finished` | 查询已完成任务 |
| `GET` | `/api/tasks/{id}/events` | SSE 任务进度事件流 |
| `GET` | `/api/tasks/{id}/result` | 获取任务结果 |
| `DELETE` | `/api/tasks/{id}` | 删除任务 |
| `POST` | `/api/tasks/{id}/deposit` | 沉淀 Web 报告到知识库 vault |
| `GET` | `/api/kb/status` | 知识库索引状态 |
| `POST` | `/api/kb/rebuild` | 重建知识库索引 |

---

## 6. 开发模式

### 后端测试

```bash
# 全部测试（离线、确定性）
uv run pytest tests/ -v

# 按关键字筛选
uv run pytest tests/ -k "event" -v
uv run pytest tests/ -k "graph" -v

# 单独测试文件
uv run pytest tests/test_event_stream.py -v
uv run pytest tests/test_web_state_graph.py -v

# 遇首个失败即停止
uv run pytest tests/ -x -q
```

### 前端测试

```bash
cd web

# 单元测试
npm run test

# E2E 测试（需先启动后端）
npm run test:e2e
```

### 前端开发

```bash
cd web

# 启动 Vite 开发服务器（热更新，5173 端口）
npm run dev

# TypeScript 检查 + 生产构建
npm run build
```

---

## 7. 常见问题

### Q: Local RAG 检索不到内容？

1. 确认知识库已索引：`uv run research-agent kb status` 检查 `file_count > 0`
2. 如未索引：`uv run research-agent kb rebuild`
3. 确认 `knowledge_base_path` 目录包含 `.md`/`.txt`/`.pdf`/`.html` 文件
4. 尝试更短的关键词或自然语言问题（支持 FTS5 关键词 + ChromaDB 语义混合检索）

### Q: Web Research 执行失败？

1. 确认 `chat_model.base_url` + `api_key` 可访问
2. 确认 `search.api_key` (Tavily) 有效
3. 检查网络连接

### Q: 配置文件在哪里？

```bash
# Windows
type %APPDATA%\research_agent\config.toml

# Linux/macOS
cat ~/.config/research_agent/config.toml
```

### Q: 如何更换 LLM 提供商？

修改 `config.toml` 中的 `base_url`、`api_key`、`model`。任何 OpenAI 兼容 API 均可使用（DeepSeek、OpenAI、SiliconFlow、Ollama、vLLM 等）。

### Q: 前端启动后页面空白？

1. 确认后端已启动（`dev:all` 需等后端 `Uvicorn running` 出现）
2. 刷新浏览器（F5）
3. 检查浏览器控制台（F12 → Console）

### Q: E2E 测试失败（`@pytest.mark.e2e`）？

E2E 测试需要真实 API key，默认被跳过。单独运行：

```bash
uv run pytest tests/test_web_e2e_simple.py -v -m e2e -s
```
