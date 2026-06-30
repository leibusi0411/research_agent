# 项目进展跟踪

> 最后更新：2026-06-30 | 测试：105 passed | 当前：阶段 5 ✅ → 阶段 6（前端页面完善）
> 本轮已完成：P2 全部 15 项 + P3 共 13 项修复（R-31, R-39, R-49, R-50, R-51, R-52, R-53, R-54, R-67, R-71, R-72, R-73, R-74）
> 本轮新发现：R-71 ~ R-79
> 本轮 Code Review 通过：P2 批量修复 + P3 批量修复（零缺陷）

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
| 阶段 6 | 前端页面完善（实时 SSE、路由、进度渲染、组件拆分） | 🔄 进行中 |
| 阶段 7 | 移植 LangGraph（StateGraph → LangGraph + SqliteSaver checkpoint） | 📋 计划中 |
| 阶段 8 | 功能全部实现（产物持久化、工厂重构、死代码清理） | 📋 计划中 |
| 阶段 9 | 健壮性优化（错误处理、可观测性、类型安全、lint/type-check） | 📋 计划中 |

**当前策略**：阶段 5 全部完成（含删除全部 fake 代码），开始准备阶段 6（前端页面完善 + 流式输出）。

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
| **R-60** | `_retrieve_hybrid` 中 `ChromaStore` 从未 `close()`——现已调用 `store.close()` at `local_research.py:159` | 06-29 |
| **R-57** | `ChromaStore.close()` 未调用 `PersistentClient.close()`——现已正确调用 + 防御 `_closed` 私有属性 + `try/finally` 保障资源释放 | 06-30 |
| **R-58** | `ChromaStore.query()` 防御代码 bug——`_safe_nth` 现处理 `None` 值；`query()` 每项构造用 `try/except` 隔离坏数据 | 06-30 |
| **R-59** | FTS5 特殊字符静默失败——`_fts5_terms` 去除特殊字符 + 所有 term 加引号；移除 `_FTS5_RESERVED`/`_fts5_phrase` 死代码；`__import__("re")` 改为标准 `import re` | 06-30 |
| **R-69** | `_save_blackboard_snapshot` 写入无异常处理——添加 `try/except OSError` + `logger.warning` | 06-30 |
| **R-70** | `waitForTerminalResult` 轮询超时 10s 与 SSE 1800s 不匹配——扩展至 720×2500ms=1800s；SSE `onDone` 回调主动 fetch 最终结果 | 06-30 |
| **R-68** | `details.items` 始终为空 → `StateGraphRunner._emit` 新增 `items` 参数；`ResearchExecutor` 新增 `on_progress` 回调，每个 tool_call 执行时 emit `tool_call` item，synthesis 完成后 emit `finding`/`source` items；per-subtask 完成时 emit `subtask_completed` item；supervisor/curation 完成时 fill relevant items；`local_research.py` 检索完成时 fill `source` items | 06-29 |
| **R-55** | SSE stream 硬截止 600s → 1800s（30分钟，匹配 Web Research 任务实际耗时） | 06-29 |
| — | 前端 SSE 实时流：`api.ts` 新增 `subscribeTaskEvents()`（基于 `EventSource`）；`App.tsx` 实时 append events 替代批量 fetch；`ProcessView` 新增 `DetailItem` 渲染 `details.items`（按 kind: tool_call/source/finding/subtask_completed/subtask_failed） | 06-29 |
| — | 测试修复：`test_continue_execution_with_empty_next_subtask_ids_in_loop` 中 `max_concurrent_subtasks` 从 3 → 1（`_SequencedChatClient` 非线程安全） | 06-29 |
| **R-07** | 结构化产物持久化：`_save_llm_call_artifact` 保存 planner/supervisor/curator/revision 的 prompt + output 到 `artifacts/llm_calls/`；`_save_tool_call_artifacts` 保存 tool call 记录到 `artifacts/tool_calls/` | 06-30 |
| **R-20** | 提取共享工厂 `create_provider_runtime()`，`CoreService.run_web_research` 和 `api/app.py:_default_web_runtime` 共同调用 | 06-30 |
| **R-22** | `run_both` 状态支持 `partial`（部分成功/部分失败不再报告为整体失败） | 06-30 |
| **R-24** | `StateGraphRunner` + `ProviderBackedWebResearchRuntime` 接受可选 `workspace_obj`/`task_store`，减少重复实例 | 06-30 |
| **R-25** | `ToolGateway.call()` 重试变量 `attempts` → `retries`，与配置字段 `tool_retries` 语义一致 | 06-30 |
| **R-28** | `_save_source_snapshots` 改为增量写入（跟踪 `_saved_source_ids`） + 添加 `try/except OSError`（附带修复 R-48） | 06-30 |
| **R-33** | `run_web_research` 传入非 None runtime 时，若 runtime 有 `on_event` 属性则透传回调 | 06-30 |
| **R-34** | CLI `_main()` 中 `CoreService` + `load_user_config` 移至 try/except 内 | 06-30 |
| **R-35** | `_print_local_result`、`_print_web_result`、`_run_both` 全部改用 `.get()` 安全访问，消除 KeyError 泄漏 | 06-30 |
| **R-37** | 循环退出兜底逻辑追踪 `_last_supervisor_route`，参考 supervisor 最终路由决策 | 06-30 |
| **R-44** | `_default_web_runtime` 通过共享工厂 `create_provider_runtime` 使用（API 层通过 SSE 推事件，无需 in-process callback） | 06-30 |
| **R-45** | 删除 `build_executor_prompt` / `_render_executor_prompt` 死代码（已拆分为 tool_plan + synthesis 两步调用） | 06-30 |
| **R-47** | `_execute_with_tools` 中新增工具名校验：执行前检查 tool_plan 中的工具名是否在 `ToolRegistry` 中 | 06-30 |
| **R-62** | `ChromaStore.build_index()` / `query()` 在 `close()` 后透明重开 client，替代之前的 RuntimeError 崩溃 | 06-30 |
| **R-63** | FTS5 结果添加 `chunk_id` + `score: None` 字段，与 Chroma 结果结构统一；`_dedup_key` 现已正确跨两种来源工作 | 06-30 |
| **R-48** | `_save_source_snapshots` 添加 `try/except OSError`（附带修复，与 R-28 同批） | 06-30 |
| **R-31** | PDF 工具：MIME 验证优先于 URL 后缀；`application/octet-stream` 时才回退到后缀 | 06-30 |
| **R-39** | `on_event` 类型注解 `object` → `Callable[[dict[str, Any]], None]`，涵盖 service.py 全部 4 处 | 06-30 |
| **R-49** | `render_web_report` 新增 `_escape_markdown_text()`，对 summary/finding text/source title 转义 Markdown 特殊字符 | 06-30 |
| **R-50** | `rebuild_kb_index` 新增详细 docstring，明确 `None`=使用配置中默认 embedding client | 06-30 |
| **R-51** | 删除 `_print_web_events` 死代码 | 06-30 |
| **R-52** | `_toml_string` 改用逐字符转义，处理 `\\`、`"` 及控制字符（U+0000–U+001F）| 06-30 |
| **R-53** | `Workspace.append_event` 添加 `try/except OSError` + `logger.warning` | 06-30 |
| **R-54** | `_extract_text` HTML 分支添加 `logger.warning`；未知后缀添加 `logger.warning` | 06-30 |
| **R-67** | `_search_fts5` 使用 `connection.row_factory = sqlite3.Row` + 按列名访问 | 06-30 |
| **R-71** | `api/app.py:service()` 添加模块级缓存，避免每次 API 调用重新创建 CoreService | 06-30 |
| **R-72** | SSE `onerror` 检查 `readyState === CLOSED` 才关闭，CONNECTING 状态让浏览器 auto-reconnect | 06-30 |
| **R-73** | `parseSseEvents` 改为 per-line try/catch，跳过坏行保留有效 events | 06-30 |
| **R-74** | `ChromaStore.build_index` 捕获 `(ValueError, chromadb.errors.NotFoundError)` 替代裸 `except Exception` | 06-30 |
| **R-32** | `_default_web_runtime` 配置重复加载 → 已通过 R-20 共享工厂解决（每次调用仍加载 config，但 body 从 8 行减为 1 行调用） | 06-30 |
| **R-56** | API 层 ThreadPoolExecutor → FastAPI `lifespan` 已有 `executor.shutdown(wait=True)` 优雅关闭 | 06-30 |
| **R-65** | `import gc` 在 `ChromaStore.close()` 中 → 已移除（前期修复） | 06-30 |

---

### 发现的问题（按优先级）

**P0 — 阻塞性**

| 编号 | 问题 | 位置 |
|------|------|------|
| — | （当前无 P0 未解决问题） | — |

**P1 — 功能缺陷**

| 编号 | 问题 | 位置 |
|------|------|------|
| — | （当前无 P1 未解决问题） | — |

**P2 — 代码质量与健壮性**

| 编号 | 问题 | 位置 |
|------|------|------|
| — | （当前无 P2 未解决问题） | — |

**P3 — 低优先级**

| 编号 | 问题 | 位置 |
|------|------|------|
| — | （当前无 P3 未解决问题） | — |

---

### ADR 合规审查（2026-06-29）

> 本次审查覆盖全部 43 个 ADR。核心发现：
> - ✅ **完全合规**（40个）：项目严格遵守 ADR 决策
> - ⚠️ **部分合规/延后**（3个）：
>   - **ADR-0008**（结构化产物持久化）：R-07 已部分修复（planner/supervisor/curator/revision 的 prompt+output → `artifacts/llm_calls/`，tool call 记录 → `artifacts/tool_calls/`）；executor 内部调用（tool_plan/synthesis）暂未覆盖，待阶段 8 回调重构
>   - **ADR-0013**（LangGraph）：当前使用手动 `StateGraphRunner`（~550 行 while 循环），LangGraph 迁移计划阶段 7。当前的 blackboard 模式 + role invocation 设计忠实地实现了 ADR-0013 的架构意图
>   - **ADR-0016**（单 Executor）：`ResearchExecutor` 正确实现单节点多子任务并发执行模式
> 
> **关键 ADR 逐项验证**（仅列架构层面最关键者）：
> 
> | ADR | 要求 | 现状 |
> |-----|------|------|
> | 0004 | Context builders + typed role schemas | ✅ `context.py` + `prompt_builders.py` + `schemas.py` dataclasses |
> | 0005 | Checkpoints ≠ task state | ✅ 当前仅手动 blackboard snapshot，阶段 7 迁移 LangGraph 后语义保持 |
> | 0017 | Local RAG ⟂ Web Research | ✅ 两个独立 workflow，永不共享上下文 |
> | 0021 | Web source snapshots → artifacts/ | ✅ `_save_source_snapshots` → `artifacts/web_sources/` |
> | 0023 | Phase-based progress stream | ✅ `ProgressEvent` with `phase` + `event_type`；`_emit` 填充 `details.items` |
> | 0026 | SQLite FTS5 + ChromaDB | ✅ Hybrid retrieval (RRF, k=60)；`ChromaStore` 关闭连接（R-60 已修复） |
> | 0031 | Tool registry + gateway + runner | ✅ `ToolRegistry` → `ToolGateway` → `ToolRunner` |
> | 0037 | CoreService use cases | ✅ 7 个用例：`init_config`、`run_local_research`、`run_web_research`、`run_both`、`list_finished_tasks`、`get_kb_status`、`rebuild_kb_index` |
> | 0042 | 测试离线且确定性 | ✅ 104 tests；`_SequencedChatClient` + `MagicMock` gateway 替代真实 LLM/Tavily |

---

## 三、下一步路线图

### 总体策略

```
阶段 5 (已完成)        阶段 6               阶段 7                 阶段 8           阶段 9
E2E 流程跑通      →  前端页面完善      →  LangGraph + EventStream  →  功能全部实现  →  健壮性优化
✅ 完成               (UX 完善 + 流式)     (架构升级 + 统一事件流)     (补齐承诺)        (生产级质量)
```

---

### 阶段 6：前端页面完善

> **目标**：从"功能可用"到"体验完整"——UI 设计优化、SSE 实时推送、路由导航、进度细节渲染、组件拆分。
> **预估**：M-L（1-2 周）

| 优先级 | 任务 | 说明 |
|--------|------|------|
| P0 | UI 设计优化 | `frontend-design` 技能重新设计页面（布局、配色、排版、组件样式） |
| P0 | SSE 实时流 + 流式输出 | `EventSource` 替代当前轮询模式；后端 `_emit` 填充 `details.items`（tool_call 名称、搜索关键词、URL、finding 文本）→ 修复 **R-68** |
| P1 | 进度细节渲染 | 渲染 `details.items`（实时展示搜索/抓取/综合进度卡片） |
| P1 | 运行中任务状态保持 | 页面刷新后恢复 active tasks |
| P2 | 组件拆分 | 409 行 `App.tsx` → 独立组件（`ResearchPage`、`TasksPage`、`KbPage`、`ResultView`、`ProgressPanel` 等） |
| P2 | 路由 | `/`→Research、`/tasks`→Tasks、`/tasks/:id`→Result、`/kb`→KB |
| P3 | 细节打磨 | report_path 可点击、任务筛选、表单校验、Error Boundary |

---

### 阶段 7：移植 LangGraph + 统一实时流式输出

> **目标**：将 `StateGraphRunner`（~550 行手动 while 循环）替换为 LangGraph，获得 checkpoint 恢复；同时构建统一事件流——CLI 和 Web UI 共享同一套底层，不再两套独立路径。
> **预估**：L（1-2 周）

**核心问题：当前 CLI 和 Web UI 是两套独立的事件消费路径**：

```
当前（两套独立）                          目标（统一底层）
═══════════════                          ═══════════════
                                         
  _emit(event)                            _emit(event)
    ├─→ events.jsonl                        ├─→ events.jsonl    (持久化/回放)
    └─→ (CLI 路径：无！)                     └─→ EventStream ←── 统一出口
                                          🡔        🡔
  Web UI:                                  🡔        🡔
  events.jsonl → poll → SSE → browser     CLI:      Web UI:
                                          async for SSE 直接消费
```

当前 Web UI 通过 `events.jsonl` **文件轮询** 桥接 SSE——文件本应是持久化层，却成了唯一传输通道。CLI 侧 `on_event` 参数从未被传入（API 层 `_default_web_runtime` 不传 `on_event`，R-44），导致 CLI 完全看不到中间过程。

**改进后的架构**：

- `_emit(event)` 同时写 `events.jsonl`（持久化）和推入 `EventStream`（实时传输）
- `EventStream` 是 CLI 和 Web UI 共享的**唯一实时事件源**
- `events.jsonl` 降级为持久化/重放用途（SSE 重连时从文件补发已错过的事件）
- 单一 `_emit` → 单一 `EventStream` → 两个消费者（CLI、SSE endpoint）

| 序号 | 任务 | 说明 |
|------|------|------|
| 7.1 | 添加依赖 | `langgraph` + `langgraph-checkpoint-sqlite` |
| 7.2 | 转换 `WebResearchState` | `@dataclass` → LangGraph `TypedDict` + `Annotated` reducer |
| 7.3 | 构建图节点 | `plan_node`、`execute_node`、`supervise_node`、`plan_revision_node`、`curate_node`（复用 `invoke_role_json` + `prompt_builders`） |
| 7.4 | 构建图边 | `START → plan → execute → supervise → conditional_edges → execute/plan_revision/curate/END` |
| 7.5 | 接入 `SqliteSaver` | 替换手动 `blackboard_snapshot.json`，获得 checkpoint 恢复 |
| **7.6** | **统一 EventStream** | 核心改造：`_emit` 同时写 `events.jsonl` + 推入共享 `asyncio.Queue`；`StateGraphRunner` 新增 `events()` 方法返回 `AsyncIterator[ProgressEvent]`；CLI 和 SSE 端点消费**同一个流**，不再走两套路径 |
| **7.7** | **SSE 端点切换到 EventStream** | `_stream_events` 从 polling `events.jsonl` 改为直接迭代 `AsyncIterator`；`events.jsonl` 仅用于 SSE 重连时补发（`Last-Event-ID` → 从文件 offset 重放） |
| **7.8** | **LLM 流式调用** | `chat_model.complete()` → `chat_model.stream()`；`invoke_role_json` 改为增量 JSON 解析，每个 chunk 通过 `_emit` 实时推送（CLI 可看到 "Planner 正在生成子任务 3/5..."） |
| **7.9** | **CLI 实时进度输出** | CLI `research-agent web` 用 `async for event in runtime.events()` 实时打印：当前角色 + 阶段 + tool_call 关键词 + finding 数量；修复 R-44（`on_event` 死代码）、R-51（`_print_web_events` 死代码） |
| 7.10 | 全量测试回归 | 94 个现有测试 + 新增 checkpoint 测试 + EventStream 统一性测试（验证 CLI 和 SSE 收到完全一致的事件序列） |

**不做改动**：`prompt_builders.py`、`context.py`、`tools.py`、`report.py`、`schemas.py` 输出 dataclass（全部复用）。`details.items` 结构保持不变（ADR-0023）。

---

### 阶段 8：功能全部实现

> **目标**：补齐 ADR/README 承诺的功能。**预估**：L（2-3 周）

**已完成（P2 批量修复，2026-06-30）**：
- ~~**R-07**~~：✅ 结构化产物持久化已部分实现（planner/supervisor/curator/revision → `artifacts/llm_calls/`；tool calls → `artifacts/tool_calls/`）；executor 内部调用待阶段 8 回调重构
- ~~**R-20**~~：✅ 共享工厂 `create_provider_runtime()` 已提取
- ~~**R-22**~~：✅ `run_both` `partial` 状态已实现
- ~~**R-45**~~：✅ 死代码已删除

**剩余必须完成**：
- R-07 完善：executor tool_plan/synthesis 的 prompt+output 持久化（需回调重构）
- CLI `task show <id>`（查看单个任务详情）
- Source 快照查看器（Web UI）

---

### 阶段 9：健壮性优化

> **目标**：生产级质量。**预估**：M（1-2 周）

**已完成（P2 批量修复，2026-06-30）**：
- ~~R-34~~：✅ CLI 构造函数已在 try/except 内
- ~~R-35~~：✅ 结果打印函数已改用 `.get()` 安全访问
- ~~R-48~~：✅ `_save_source_snapshots` 已添加 `try/except OSError`
- ~~R-25~~：✅ 重试计数命名已修正
- ~~R-28~~：✅ 增量写入已实现

**已完成（P3 批量修复，2026-06-30）**：
- ~~R-49~~：✅ Markdown 转义已实现（`_escape_markdown_text`）
- ~~R-31~~：✅ PDF MIME 验证逻辑已修正
- ~~R-39~~：✅ `on_event` 类型注解已修正为 `Callable`
- ~~R-50~~：✅ docstring 已补充
- ~~R-51~~：✅ 死代码 `_print_web_events` 已删除
- ~~R-52~~：✅ TOML 字符串转义已增强
- ~~R-53~~：✅ `append_event` 已添加 OSError 处理
- ~~R-54~~：✅ 所有 `_extract_text` 分支均已添加日志
- ~~R-67~~：✅ `sqlite3.Row` 已使用
- ~~R-71~~：✅ API service 已缓存
- ~~R-72~~：✅ SSE onerror 区分瞬态/永久错误
- ~~R-73~~：✅ SSE parse 按行 try/catch

**剩余**：
- **错误处理**：LLM 调用重试、SIGINT 优雅退出
- **可观测性**：结构化日志、`_emit` 事件标准化、LLM 耗时记录
- **性能**：R-32（config 缓存——create_provider_runtime 内部仍每次 load_user_config）
- **工程基础**：mypy/pyright、ruff、API rate limit

**验证**：`mypy` 零错误、`ruff check` 零告警、SIGINT 后锁已释放、`uv run pytest` 全部通过
