# 项目进展跟踪

> 最后更新：2026-06-25（第三轮 review — 修复待处理问题）
> 测试：104 passed | ADR 合规率：~97%（P0 问题已全部修复）

---

## 一、项目阶段总览

| 阶段 | 目标 | 状态 | 核心交付物 |
|------|------|------|-----------|
| 阶段 1 | 基础设施 | ✅ 完成 | Config、Workspace、TaskStorage、KB Indexing |
| 阶段 2 | Local RAG | ✅ 完成 | SQLite FTS5 检索、CLI 集成 |
| 阶段 3 | Web Research 骨架 | ✅ 完成 | Schemas、Context Builders、ToolGateway、FakeRuntime、Report Writer |
| 阶段 4 | Web Research 真实运行时 | ✅ 完成 | Prompt Builders、StateGraphRunner、ResearchExecutor、Blackboard/Source 快照、ProviderBackedWebResearchRuntime |
| 阶段 5 | 端到端验证 | 🔄 进行中 | 真实 LLM 集成测试 ✅ (104 tests passed)、性能优化、错误处理增强 |

### 阶段 4 详细完成情况

| 组件 | 文件 | 状态 |
|------|------|------|
| Prompt Builders | `web/prompt_builders.py` | ✅ |
| StateGraphRunner | `web/state_graph.py` | ✅ |
| ResearchExecutor | `web/state_graph.py` | ✅ |
| Blackboard 快照 | `web/state_graph.py:431` | ✅ |
| Source 快照 | `web/state_graph.py:448` | ✅ |
| ProviderBackedWebResearchRuntime | `web/provider_runtime.py` | ✅ |

### 阶段 5 进行中

| 组件 | 文件 | 状态 |
|------|------|------|
| 端到端集成测试 | `tests/test_web_e2e.py` | ✅ |
| 端到端简单测试 | `tests/test_web_e2e_simple.py` | ✅ |
| Executor 工具调用集成 | `web/state_graph.py` | ✅ |
| 多步骤工具调用流程 | `web/state_graph.py` + `web/prompt_builders.py` | ✅ |

---

## 二、上次 Review 发现的问题（2026-06-24）

### 已修复

| 编号 | 问题 | 修复日期 |
|------|------|----------|
| F-01 | CoreService 方法签名使用 `*args, **kwargs`，替换为显式类型参数 | 2026-06-24 |
| F-02 | API 层锁泄漏 — `executor.submit()` 失败时锁不释放 | 2026-06-24 |
| F-03 | 死代码 `_public_result`（api/app.py）已删除 | 2026-06-24 |
| F-04 | 死代码 `_print_web_events`（cli.py）已删除 | 2026-06-24 |
| F-05 | TOML 转义不完整 — `_toml_string()` 已增强 | 2026-06-24 |
| F-06 | PDF 提取失败静默吞掉错误 — 已添加 `logger.warning` | 2026-06-24 |
| F-07 | `_run_background` 后台任务异常静默丢失 — 已添加 `logger.exception` | 2026-06-25 |
| F-08 | `kb.py` 中 `logger` 定义位于 import 之间 — 已移到 import 之后 | 2026-06-25 |
| F-09 | Local RAG 全表加载 + 纯词频计数 — 已改用 FTS5 MATCH + rank 排序 + LIMIT 10 | 2026-06-25 |
| F-10 | SSE 流 30 秒截止太短 — 已改为 10 分钟 + 超时事件 | 2026-06-25 |
| F-11 | `_run_family_result` ValueError 未处理 — `run_both` 中 `future.result()` 已用 try/except 包裹 | 2026-06-25 |
| F-12 | `_toml_string` 未转义控制字符 — 已添加 `\uXXXX` 回退转义 | 2026-06-25 |
| F-13 | 后台任务无优雅关闭 — 已添加 FastAPI lifespan 事件 | 2026-06-25 |
| F-14 | CLI 硬编码 FakeWebResearchRuntime — 已改为默认使用 provider-backed | 2026-06-25 |
| F-15 | Prompt Builders 未实现 | 2026-06-25 |
| F-16 | LangGraph StateGraph 未实现 | 2026-06-25 |
| F-17 | ProviderBackedWebResearchRuntime 是空壳 | 2026-06-25 |
| F-18 | blackboard_snapshot.json 未写入 | 2026-06-25 |
| F-19 | artifacts/web_sources/ 快照未填充 | 2026-06-25 |
| F-20 | **Bug: `_default_web_runtime` 缺少必需参数 `tool_gateway`** — 已修复，创建完整的 ToolGateway 并传入 | 2026-06-25 |
| F-21 | **Executor 未调用工具** — 已修复，实现多步骤工具调用流程（plan → execute → synthesize） | 2026-06-25 |
| F-22 | **`build_executor_context` 缺少错误处理** — 已修复，`next()` 添加默认值和有意义的错误信息 | 2026-06-25 |
| F-23 | **`_post_json` 方法重复** — 已修复，提取为共享的 `_post_json_request` 函数 | 2026-06-25 |
| F-24 | **`_file_signature` 双重 `stat()` 调用** — 已修复，缓存 `stat()` 结果 | 2026-06-25 |
| F-25 | **`TaskRecord(*row)` 脆弱的列映射** — 已修复，使用 `sqlite3.Row` 和列名访问 | 2026-06-25 |
| F-26 | **类型注解 `object | None` 丧失类型安全** — 已修复，定义 `WebResearchRuntime` Protocol | 2026-06-25 |
| F-27 | **`prompt_builders.py` 与 `context.py` 代码重复** — 已修复，使用 `build_executor_context` 和 `build_planner_context` | 2026-06-25 |
| F-28 | **R-09 导致 4 个测试失败** — 已修复，更新测试 mock 响应以匹配新的 2-LLM-call executor 流程 | 2026-06-25 |
| F-29 | **`_build_manifest` 双重 `stat()` 调用** — 已修复，缓存 `parsed.path.stat()` 结果 | 2026-06-25 |
| F-30 | **`_default_web_runtime` 忽略 config 值** — 已修复，传递 `max_retrieval_rounds` 和 `max_concurrent_subtasks` | 2026-06-25 |
| F-31 | **未使用的导入和死代码** — 已修复，移除 `state_graph.py` 中未使用的导入 | 2026-06-25 |
| F-32 | **`rebuild_kb_index` 类型注解不安全** — 已修复，使用 `EmbeddingClient | None` 替代 `object | None` | 2026-06-25 |

### 待修复

| 编号 | 问题 | 优先级 |
|------|------|--------|
| R-07 | 结构化产物（tool call 记录、model usage metadata）未持久化 | P2 |

---

## 三、文档与代码不一致（2026-06-25 第二轮 review 发现）

| 编号 | 不一致点 | 建议 |
|------|----------|------|
| D-01 | CLAUDE.md 引用 `FUTURE_UPGRADES.md`，实际文件为 `TODO.md` | ✅ 已修复 — 更新 CLAUDE.md 引用为 `TODO.md` |
| D-02 | CLAUDE.md 架构图引用 `web/runtime.py`，实际拆分为 `fake_runtime.py` 和 `provider_runtime.py` | ✅ 已修复 — 更新架构图为 `fake_runtime, provider_runtime` |
| D-03 | REVIEW_TRACKER.md 此前引用 `core/local.py`，实际文件为 `core/local_research.py` | 已在本次 review 中修正 |
| D-04 | CONTEXT.md 描述"Chroma 向量索引"，实际为 SQLite 表存储 JSON 序列化嵌入，非真正 Chroma 数据库 | 更新文档说明这是简化实现 |

### 第三轮 review 补充发现（2026-06-25）

| 编号 | 不一致点 | 状态 |
|------|----------|------|
| D-05 | `state_graph.py` 中 `build_executor_prompt` 导入但未使用 | ✅ 已修复 — 移除未使用导入 |
| D-06 | `state_graph.py` 中 `ToolResult` 导入但未使用 | ✅ 已修复 — 移除未使用导入 |
| D-07 | `prompt_builders.py` 未使用 `build_supervisor_context`/`build_curator_context` | ✅ 已修复 — 统一使用 context builders |

---

## 四、测试覆盖缺口

| 缺口 | 说明 | 优先级 |
|------|------|--------|
| `_default_web_runtime` | R-08 已修复，但该函数仍无直接测试覆盖 | P1 |
| `ProviderBackedWebResearchRuntime` 集成 | 所有 web 测试使用 FakeRuntime 或直接 mock chat_model，无真实 runtime 集成测试 | P1 |
| 并发任务执行 | 无两个不同 family 任务同时运行的测试 | P2 |
| SSE 流超时 | 无 10 分钟超时行为的测试 | P2 |
| SIGINT/优雅关闭 | 无信号处理和 graceful shutdown 测试 | P2 |
| `test_api_connections.py` 标记 | 测试真实 API 但无 `e2e` 标记，默认运行时会因缺少 API key 失败 | P1 |
| 工具调用失败回退 | R-09 新增的多步骤工具调用流程缺少工具调用失败时的回退机制测试 | P2 |

---

## 五、下一步工作

### 近期（P0 — 阻塞真实运行）

1. ✅ **修复 `_default_web_runtime` 缺少 `tool_gateway`**（R-08）— 已修复
2. ✅ **Executor 集成 ToolGateway**（R-09）— 已修复，实现多步骤工具调用流程
3. ✅ **端到端集成测试** — 使用真实 LLM 验证完整 Web Research 流程（3 个测试用例）

### 中期（P1-P2）

1. ✅ **`build_executor_context` 错误处理**（R-10）— 已修复
2. **结构化产物持久化**（R-07）— 记录 tool call 和 model usage metadata
3. **测试覆盖补充** — `_default_web_runtime`、并发任务、SSE 流超时、SIGINT 处理、工具调用失败回退等
4. **错误处理增强** — 网络超时、API 限流、模型输出异常、工具调用失败的处理
5. **`_default_web_runtime` 测试覆盖** — 添加直接单元测试

### 低优先级（P3）

1. ✅ **代码质量** — `_post_json` 去重（R-11）、`_file_signature` 优化（R-12）、类型注解改进（R-14）— 已修复
2. **文档修正** — Chroma 说明（D-04）— 更新文档说明这是简化实现
3. **工具调用数量上限** — 添加 `max_tool_calls_per_plan` 配置或硬编码限制

---

## 附录：ADR 合规矩阵

| ADR | 标题 | 状态 | 备注 |
|-----|------|------|------|
| 0001 | 技术栈选择 | ✅ | Python/FastAPI/React/SQLite |
| 0002 | 单用户、本地优先 | ✅ | |
| 0003 | SQLite 任务存储 + 文件结果 | ✅ | |
| 0004 | Context Builder + 类型化 Schema | ✅ | |
| 0005 | LangGraph 检查点与 Task State 分离 | ✅ | blackboard_snapshot.json 已实现 |
| 0006 | 知识库只读导入 | ✅ | |
| 0007 | 通过 Search Provider 接口使用 Tavily | ✅ | |
| 0008 | 持久化结构化产物 | ⚠️ | blackboard/source 快照已实现，tool call 记录待实现（R-07） |
| 0009 | TOML 配置 | ✅ | |
| 0010 | 本地主机 Web UI | ✅ | |
| 0011 | CLI 流式输出，无需守护进程 | ✅ | |
| 0012 | 分层包结构 + 独立 Web 应用 | ✅ | |
| 0013 | LangGraph 状态图 + Blackboard 模式 | ✅ | StateGraphRunner 已实现 |
| 0014 | Supervisor 就绪性验证 + Curator Schema | ✅ | |
| 0015 | 工具网关 | ✅ | ToolGateway 已实现，Executor 已集成工具调用 |
| 0016 | 单一 ResearchExecutor | ✅ | ResearchExecutor 已实现并集成工具调用 |
| 0017 | 独立的 Local RAG / Web Research 模式 | ✅ | |
| 0018 | 写入 Web 报告文件 | ✅ | |
| 0019 | Markdown 报告 | ✅ | |
| 0020 | 报告模板 | ✅ | |
| 0021 | Web Source 快照作为产物 | ✅ | web_sources 快照已实现 |
| 0022 | 预构建的 Local RAG 索引 | ✅ | |
| 0023 | 基于阶段的进度流 | ✅ | |
| 0024 | 全局默认工作区 | ✅ | |
| 0025 | 仅支持 OpenAI 兼容 Provider | ✅ | |
| 0026 | SQLite FTS5 + 向量索引 | ✅ | FTS5 检索已实现 |
| 0027 | httpx + trafilatura | ✅ | |
| 0028 | 列出已完成任务，无删除 | ✅ | |
| 0029 | 按模式分离结果页面 | ✅ | |
| 0030 | 设置视图，无设置页面 | ✅ | |
| 0031 | 函数调用工具 + Registry/Gateway/Runner | ✅ | Executor 已集成工具调用（多步骤流程） |
| 0032 | 节点 Prompt 作为代码常量 | ✅ | 6 个 prompt builder 已实现（planner, executor_tool_plan, executor_synthesis, supervisor, curator, revision_planner） |
| 0033 | pypdf 用于 PDF 提取 | ✅ | |
| 0034 | 简单本地 ID + UTC 时间戳 | ✅ | |
| 0035 | 宽松的逐工具工程边界 | ✅ | |
| 0036 | 独立的 Local RAG / Web Research | ✅ | |
| 0037 | Core Service 用例 | ✅ | |
| 0038 | 最小化 FastAPI + SSE 接口 | ✅ | `_default_web_runtime` 已修复 |
| 0039 | 统一的研究错误对象 | ✅ | |
| 0040 | 人类可读的 CLI 输出 | ✅ | |
| 0041 | 垂直实现阶段 | ✅ | 阶段 1-4 完成 |
| 0042 | 确定性离线测试 | ✅ | |
| 0043 | Python 用 uv，Web UI 用 npm | ✅ | |
