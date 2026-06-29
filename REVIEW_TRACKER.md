# 项目进展跟踪

> 最后更新：2026-06-29 | 测试：94 passed | 当前：阶段 5 ✅ → 阶段 6
> 本轮已完成：R-13 ~ R-43、R-46、R-61、R-64、R-66、D-04（详见下方汇总）

 - R = Review Issue | P = Priority（P0 阻塞 / P1 重要 / P2 改进 / P3 低优先级）

---

## 一、项目阶段与当前状态

| 阶段 | 目标 | 状态 |
|------|------|------|
| 阶段 1 | 基础设施（Config、Workspace、TaskStorage、KB Indexing） | ✅ |
| 阶段 2 | Local RAG（SQLite FTS5 检索、CLI） | ✅ |
| 阶段 3 | Web Research 骨架（Schemas、Context、ToolGateway、StateGraph、Report） | ✅ |
| 阶段 4 | Web Research 真实运行时（Prompt Builders、StateGraphRunner、ProviderRuntime） | ✅ |
| 阶段 5 | 端到端流程跑通（正确性、边界情况、锁恢复、删除 fake 代码） | ✅ |
| 阶段 6 | 移植 LangGraph（StateGraph → LangGraph + SqliteSaver checkpoint） | 📋 计划中 |
| 阶段 7 | 前端页面完善（实时 SSE、路由、进度渲染、组件拆分） | 📋 计划中 |
| 阶段 8 | 功能全部实现（产物持久化、工厂重构、死代码清理） | 📋 计划中 |
| 阶段 9 | 健壮性优化（错误处理、可观测性、类型安全、lint/type-check） | 📋 计划中 |

**当前策略**：阶段 5 全部完成（含删除全部 fake 代码），开始准备阶段 6。

---

## 二、本轮 Review（2026-06-29）

### 已完成修复（汇总）

| 编号 | 问题 | 日期 |
|------|------|------|
| R-13 | FTS5 索引已构建但检索从未使用 → 实现 FTS5 MATCH + ChromaDB RRF 融合检索 | 06-29 |
| R-14 | 角色级模型覆盖：链路重构为 `dict[str, ChatModelClient]` 按角色传递 | 06-29 |
| R-15 | 真实 Runtime 无进度回调 | 06-26 |
| R-16 | Supervisor `next_subtask_ids` 被忽略 | 06-26 |
| R-17 | CLI 不捕获非 ResearchError 异常 | 06-26 |
| R-18 | Schema repair LLM 调用无异常保护 | 06-26 |
| R-19 | 空 `tool_calls` 时 Executor 仍尝试合成 | 06-29 |
| R-21 | `chat_model` 参数类型 → `dict[str, ChatModelClient]` | 06-29 |
| R-23 | StateGraphRunner 与 API 层双重调用 `create_task_folder` | 06-29 |
| R-26 | Supervisor `continue_execution` + 空 `next_subtask_ids` 行为不一致 | 06-29 |
| R-27 | 崩溃后锁文件残留，无法自动恢复 | 06-29 |
| R-29 | `_retrieve_local_results` 全表扫描 → FTS5 MATCH + ChromaDB RRF | 06-29 |
| R-30 | `local_research.py` 事件字段不完整 | 06-29 |
| R-36 | `_guard_route` 不守卫 `revise_plan`（StateGraphRunner 侧） | 06-29 |
| R-38 | `_next_target_ids` 过滤逻辑无测试覆盖 | 06-29 |
| R-40 | `revise_plan` 分支 `_next_target_ids = None` 冗余 | 06-29 |
| R-41 | `list(next_subtask_ids)` 不必要的浅拷贝 | 06-29 |
| R-42 | Schema repair LLM 调用失败场景无测试覆盖 | 06-29 |
| R-43 | `FakeRuntime._guard_route` 不守卫 `revise_plan` | 06-29 |
| R-46 | `FakeChatModelClient` 线程不安全 → 随 fake 代码删除 | 06-29 |
| R-61 | `_DeterministicEmbeddingClient` 所有文本返回相同向量 → 随 fake 代码删除 | 06-29 |
| R-64 | `FakeWebResearchRuntime._guard_route` 缺测试覆盖 → 随 fake 代码删除 | 06-29 |
| R-66 | 两种"确定性嵌入"命名混淆 → `_DeterministicEmbeddingClient` 已删除 | 06-29 |
| D-04 | CONTEXT.md 更新为 "ChromaDB persistent vector index" | 06-29 |
| — | 全部 fake 代码删除（`fake_runtime.py`、`FakeChatModelClient`、`InMemoryHttpClient`、`_DeterministicEmbeddingClient`、`FixedEmbeddingClient`、环境变量门控） | 06-29 |
| — | LLM 调用添加 `temperature=0.1`、`max_tokens=16384`、`response_format: json_object` | 06-29 |
| — | httpx LLM 请求超时从 60s → read=300s（修复 curator 大响应超时） | 06-29 |

---

### 发现的问题（按优先级）

**P0 — 阻塞性**

| 编号 | 问题 | 位置 |
|------|------|------|
| **R-57** | `ChromaStore.close()` 未调用 `PersistentClient.close()`——Windows 上 KB 重建时 `shutil.copytree` 可能因文件锁失败 | `core/chroma_store.py:33` |
| **R-58** | `ChromaStore.query()` 防御代码自身有 bug——`(results.get("metadatas") or [{}])[0][idx]` 在 metadatas 缺失时抛出 KeyError | `core/chroma_store.py:114` |
| **R-59** | FTS5 查询对特殊字符静默失败——`*` `(` `)` 及保留字 `AND` `OR` `NOT` 导致 `sqlite3.OperationalError`，被静默捕获返回 `[]` | `core/local_research.py:67,90` |

**P1 — 功能缺陷**

| 编号 | 问题 | 位置 |
|------|------|------|
| **R-60** | `_retrieve_hybrid` 中 `ChromaStore` 从未 `close()`——长驻 FastAPI 进程每次检索泄漏 SQLite 连接 | `core/local_research.py:128` |

**P2 — 代码质量与健壮性**

| 编号 | 问题 | 位置 |
|------|------|------|
| R-07 | 结构化产物（tool call 记录、model usage metadata）未持久化到 `artifacts/` | — |
| R-20 | `CoreService.run_web_research` 与 `_default_web_runtime` 代码重复 | `core/service.py:53` / `api/app.py:266` |
| R-22 | `run_both` 部分成功被报告为整体失败（需要 `partial` 状态） | `core/service.py:90` |
| R-24 | 链路中 3 个独立 Workspace 实例，功能正确但认知负担高 | 多处 |
| R-25 | ToolGateway 重试计数与配置名语义有偏差 | `web/tools.py:244` |
| R-28 | `_save_source_snapshots` 每轮全量重写所有 source 文件 | `web/state_graph.py:532` |
| R-33 | `run_web_research` 传入非 None runtime 时静默忽略 `on_event` | `core/service.py:49` |
| R-34 | CLI 中 Runtime/Service 构造函数在 try/except 之外 | `cli.py` |
| R-35 | 结果打印函数在 try/except 边界外，KeyError 可泄漏 | `cli.py:156,196` |
| R-37 | 循环退出兜底逻辑未参考 supervisor 最终路由 | `web/state_graph.py:427` |
| R-44 | `_default_web_runtime` 未透传 `on_event` 回调 | `api/app.py:266` |
| R-45 | `build_executor_prompt` / `_render_executor_prompt` 死代码 | `web/prompt_builders.py:25,105` |
| R-47 | `_validate_tool_plan_payload` 不校验工具名是否在 ToolRegistry 中 | `web/state_graph.py:64` |
| R-62 | `ChromaStore.build_index()` 在 `close()` 后调用会崩溃 | `core/chroma_store.py:48` |
| R-63 | RRF 融合结果字段结构不一致（FTS5 vs Chroma 条目字段不同） | `core/local_research.py:137` |
| **R-68** | `details.items` 始终为空——ADR-0023 定义了 tool_call/source/finding 三种 items，但 `StateGraphRunner._emit` 从未填充；子任务执行无 `progress` 事件，CLI 只看到 `"Executing N subtasks"` → `"Subtasks executed"` | `web/state_graph.py:339,365,370,379,389` |

**P3 — 低优先级**

| 编号 | 问题 | 位置 |
|------|------|------|
| R-31 | PDF 工具 URL 后缀优先于 MIME 验证 | `web/tools.py:229` |
| R-32 | `_default_web_runtime` 每次重新加载 config | `api/app.py:267` |
| R-39 | `on_event` 类型注解应为 `Callable`，当前为 `object` | `core/service.py:49` |
| R-48 | `_save_source_snapshots` 写入无异常处理 | `web/state_graph.py:532` |
| R-49 | `render_web_report` 不转义 Markdown 特殊字符 | `web/report.py:42` |
| R-50 | `CoreService.rebuild_kb_index` 的 `embedding_client` 参数语义不清晰 | `core/service.py:102` |
| R-51 | `_print_web_events` 死代码——定义于 `cli.py:283`，从未调用 | `cli.py:283` |
| R-52 | `_render_config_toml` 字符串拼接生成 TOML，特殊字符可能生成无效文件 | `core/config.py:261` |
| R-53 | `Workspace.append_event` 无错误处理 | `core/workspace.py` |
| R-54 | `_extract_text` PDF 提取静默吞错误，无日志 | `core/kb.py` |
| R-55 | SSE 流 `_stream_events` 有 30 秒硬截止 | `api/app.py` |
| R-56 | API 层 `ThreadPoolExecutor` 无优雅关闭 | `api/app.py` |
| R-65 | `import gc` 在 `ChromaStore.close()` 方法内部 | `core/chroma_store.py:40` |
| R-67 | `_search_fts5` 使用索引访问 row[0]~row[4]，应用 `sqlite3.Row` | `core/local_research.py:94` |

---

### ADR 合规审查历史（2026-06-24）

> 合并自已删除的 `docs/review/`。审查时项目处于 Phase 3，Phase 4/5 后所有的 11 项"部分合规"已全部补齐。

---

## 三、下一步路线图

### 总体策略

```
阶段 5 (已完成)        阶段 6            阶段 7           阶段 8           阶段 9
E2E 流程跑通      →   移植 LangGraph  →  前端页面完善  →  功能全部实现  →  健壮性优化
✅ 完成               (架构升级)         (UX 完善)        (补齐承诺)        (生产级质量)
```

---

### 阶段 6：移植 LangGraph

> **目标**：将 `StateGraphRunner`（~550 行手动 while 循环）替换为 LangGraph，获得 checkpoint 恢复 + `astream_events` 流式输出。
> **预估**：L（1-2 周）

| 序号 | 任务 | 说明 |
|------|------|------|
| 6.1 | 添加依赖 | `langgraph` + `langgraph-checkpoint-sqlite` |
| 6.2 | 转换 `WebResearchState` | `@dataclass` → LangGraph `TypedDict` + `Annotated` reducer |
| 6.3 | 构建图节点 | `plan_node`、`execute_node`、`supervise_node`、`plan_revision_node`、`curate_node`（复用 `invoke_role_json` + `prompt_builders`） |
| 6.4 | 构建图边 | `START → plan → execute → supervise → conditional_edges → execute/plan_revision/curate/END` |
| 6.5 | 接入 `SqliteSaver` | 替换手动 `blackboard_snapshot.json`，获得 checkpoint 恢复 |
| 6.6 | 保持进度事件 | `_emit` 通过 `astream_events` 保持，同步修复 **R-68**（填充 `details.items`） |
| 6.7 | 更新 `ProviderBackedWebResearchRuntime` | 构造 `StateGraphRunner` → 构造 LangGraph compiled graph |
| 6.8 | 全量测试回归 | 94 个现有测试 + 新增 checkpoint 测试 |

**不做改动**：`prompt_builders.py`、`context.py`、`tools.py`、`role_invocation.py`、`report.py`、`schemas.py` 输出 dataclass（全部复用）。

---

### 阶段 7：前端页面完善

> **目标**：从"功能可用"到"体验完整"——SSE 实时推送、路由导航、进度细节渲染、组件拆分。
> **预估**：M-L（1-2 周）

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P1 | SSE 实时流 | `EventSource` 替代当前轮询模式 |
| P1 | 进度细节渲染 | 渲染 `details.items`（tool_call 名称、搜索关键词、URL、finding 文本）——依赖 R-68 |
| P1 | 运行中任务状态保持 | 页面刷新后恢复 active tasks |
| P2 | 组件拆分 | 409 行 `App.tsx` → 独立组件 |
| P2 | 路由 | `/`→Research、`/tasks`→Tasks、`/tasks/:id`→Result、`/kb`→KB |
| P3 | 细节打磨 | report_path 可点击、任务筛选、表单校验、Error Boundary |

---

### 阶段 8：功能全部实现

> **目标**：补齐 ADR/README 承诺的功能。**预估**：L（2-3 周）

**必须完成**：
- **R-07**：结构化产物持久化（prompt + raw_output + tool_call 记录 → `artifacts/`）
- **R-20**：提取共享 Runtime 工厂 `create_provider_runtime(config, workspace, on_event)`，同时修复 R-44
- **R-45**：删除 `build_executor_prompt` / `_render_executor_prompt` 死代码

**建议完成**：
- CLI `task show <id>`（查看单个任务详情）
- `run_both` 引入 `partial` 状态（R-22）
- Source 快照查看器（Web UI）

---

### 阶段 9：健壮性优化

> **目标**：生产级质量。**预估**：M（1-2 周）

**错误处理**：R-34、R-35、R-48、R-49、LLM 调用重试、SIGINT 优雅退出
**可观测性**：结构化日志、`_emit` 事件标准化、LLM 耗时记录
**性能**：R-28（增量写入）、R-25（重试语义）、R-32（config 缓存）
**工程基础**：mypy/pyright、ruff、API rate limit

**验证**：`mypy` 零错误、`ruff check` 零告警、SIGINT 后锁已释放、`uv run pytest` 全部通过
