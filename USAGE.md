# Research Agent 使用指南

## 目录

- [1. 环境准备](#1-环境准备)
- [2. 初始化配置](#2-初始化配置)
- [3. 配置文件说明](#3-配置文件说明)
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

### 方式 B：Web UI

启动后浏览器访问；未配置时落在 Research 页（照常可浏览与输入），启动调研时才同步报 `config_missing`，可随时从侧边栏进入 Settings 页面完成配置。

### 方式 B：手动创建配置文件

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
# Web Research 启动前注入本地知识库检索结果（Prior Knowledge）给 Planner，
# 让调研瞄准本地未覆盖的缺口；设为 false 则回到完全独立的纯网络调研
inject_local_context = true

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
# Local RAG 总结与查询改写专用模型（可选，ADR-0052）
# 配置此节即启用 Multi-Query 查询改写；不配则不改写、总结回退全局模型。
# 省略的字段继承上方 [chat_model] 的对应值
# base_url = "https://api.deepseek.com"
# api_key = "sk-xxx"
# model = "deepseek-chat"

[embedding_model]
provider = "openai_compatible"
base_url = "https://api.siliconflow.cn/v1"
api_key = "sk-xxx"
model = "Qwen/Qwen3-VL-Embedding-8B"

[search]
provider = "tavily"
api_key = "tvly-xxx"

[rerank_model]
# Cross-Encoder 精排模型端点（可选，ADR-0053）——配置此节即启用 rerank，
# 不配则不做精排（保持 RRF 融合顺序）；API 失败自动降级回融合顺序
provider = "rerank_api"
base_url = "https://api.siliconflow.cn/v1"
api_key = "sk-xxx"
model = "BAAI/bge-reranker-v2-m3"

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

## 4. Web UI 使用

### 启动 Web 应用

```bash
# 进入 web 目录
cd web

# 一键启动前后端（推荐）
npm run dev:all
```

浏览器访问 **http://127.0.0.1:5173**

未配置时落在 Research 页（可正常浏览与输入，启动调研时才报 `config_missing`）；从侧边栏进入 Settings 配置页面填写提交后，即可使用全部四个页面：

| 页面 | 路由 | 功能 |
|------|------|------|
| **Research** | `/` | 输入问题启动 Web Research，实时查看进度和结果（Local RAG 请到 Knowledge Base 页，或用 API） |
| **Tasks** | `/tasks` | 查看历史任务列表，点击行内展开详情，可删除已完成任务 |
| **Knowledge Base** | `/kb` | 查看/重建索引，直接提问 Local RAG |
| **Settings** | `/settings` | 随时查看和修改全部配置（已保存的 API key 留空即保持不变） |

### 生产模式部署

```bash
# 1. 构建前端
cd web && npm run build && cd ..

# 2. 启动后端（仅 API，不服务前端静态文件）
uv run uvicorn research_agent.api.app:create_app --factory --host 127.0.0.1 --port 8000
```

后端只提供 API；`web/dist/` 需用任意静态服务器自行托管，并将 `/api` 反向代理到后端端口。日常开发推荐 `npm run dev:all`（见上）。

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

## 5. 开发模式

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

## 6. 常见问题

### Q: Local RAG 检索不到内容？

1. 确认知识库已索引：Knowledge Base 页检查 `file_count > 0`
2. 如未索引：Knowledge Base 页点 Rebuild
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
