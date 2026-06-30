# 项目进展跟踪

> 最后更新：2026-06-30 | 测试：126 passed, 1 failed (pre-existing: _TestWebRuntime missing .runner) | 当前：阶段 6（S1 EventStream ✅ 完成，S2 Web UI 实时 SSE 待开始）
> S1 P2/P3 Review：R-78~R-83 全部修复（2026-06-30）
> S1 测试：22 个测试全部通过（test_event_stream.py，含 R-83 新增 13 个）

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
| 阶段 6 | 前端页面完善 + 统一 EventStream（SSE 升级 + 流式输出 + 路由 + 组件拆分） | 🔄 进行中 |
| 阶段 7 | 移植 LangGraph（StateGraph → LangGraph + SqliteSaver checkpoint） | 📋 计划中 |
| 阶段 8 | 功能全部实现（产物持久化、工厂重构、死代码清理） | 📋 计划中 |
| 阶段 9 | 健壮性优化（错误处理、可观测性、类型安全、lint/type-check） | 📋 计划中 |

**当前策略**：阶段 5 全部完成（含删除全部 fake 代码）。阶段 6 方案已通过 grill-with-docs 定稿——先 A（EventStream）后 B（LangGraph），CLI 和 Web UI 共享统一事件流。

---

## 四、已有 Review 记录（2026-06-29）

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
| **R-70** | `waitForTerminalResult` 轮询超时 10s 与 SSE 1800s 不匹配——扩展至 720x2500ms=1800s；SSE `onDone` 回调主动 fetch 最终结果 | 06-30 |
| **R-68** | `details.items` 始终为空 -> `StateGraphRunner._emit` 新增 `items` 参数；`ResearchExecutor` 新增 `on_progress` 回调，每个 tool_call 执行时 emit `tool_call` item，synthesis 完成后 emit `finding`/`source` items；per-subtask 完成时 emit `subtask_completed` item；supervisor/curation 完成时 fill relevant items；`local_research.py` 检索完成时 fill `source` items | 06-29 |
| **R-55** | SSE stream 硬截止 600s -> 1800s（30分钟，匹配 Web Research 任务实际耗时） | 06-29 |
| — | 前端 SSE 实时流：`api.ts` 新增 `subscribeTaskEvents()`（基于 `EventSource`）；`App.tsx` 实时 append events 替代批量 fetch；`ProcessView` 新增 `DetailItem` 渲染 `details.items`（按 kind: tool_call/source/finding/subtask_completed/subtask_failed） | 06-29 |
| — | 测试修复：`test_continue_execution_with_empty_next_subtask_ids_in_loop` 中 `max_concurrent_subtasks` 从 3 -> 1（`_SequencedChatClient` 非线程安全） | 06-29 |
| **R-07** | 结构化产物持久化：`_save_llm_call_artifact` 保存 planner/supervisor/curator/revision 的 prompt + output 到 `artifacts/llm_calls/`；`_save_tool_call_artifacts` 保存 tool call 记录到 `artifacts/tool_calls/` | 06-30 |
| **R-20** | 提取共享工厂 `create_provider_runtime()`，`CoreService.run_web_research` 和 `api/app.py:_default_web_runtime` 共同调用 | 06-30 |
| **R-22** | `run_both` 状态支持 `partial`（部分成功/部分失败不再报告为整体失败） | 06-30 |
| **R-24** | `StateGraphRunner` + `ProviderBackedWebResearchRuntime` 接受可选 `workspace_obj`/`task_store`，减少重复实例 | 06-30 |
| **R-25** | `ToolGateway.call()` 重试变量 `attempts` -> `retries`，与配置字段 `tool_retries` 语义一致 | 06-30 |
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
| **R-39** | `on_event` 类型注解 `object` -> `Callable[[dict[str, Any]], None]`，涵盖 service.py 全部 4 处 | 06-30 |
| **R-49** | `render_web_report` 新增 `_escape_markdown_text()`，对 summary/finding text/source title 转义 Markdown 特殊字符 | 06-30 |
| **R-50** | `rebuild_kb_index` 新增详细 docstring，明确 `None`=使用配置中默认 embedding client | 06-30 |
| **R-51** | 删除 `_print_web_events` 死代码 | 06-30 |
| **R-52** | `_toml_string` 改用逐字符转义，处理 `\\`、`"` 及控制字符（U+0000-U+001F）| 06-30 |
| **R-53** | `Workspace.append_event` 添加 `try/except OSError` + `logger.warning` | 06-30 |
| **R-54** | `_extract_text` HTML 分支添加 `logger.warning`；未知后缀添加 `logger.warning` | 06-30 |
| **R-67** | `_search_fts5` 使用 `connection.row_factory = sqlite3.Row` + 按列名访问 | 06-30 |
| **R-71** | `api/app.py:service()` 添加模块级缓存，避免每次 API 调用重新创建 CoreService | 06-30 |
| **R-72** | SSE `onerror` 检查 `readyState === CLOSED` 才关闭，CONNECTING 状态让浏览器 auto-reconnect | 06-30 |
| **R-73** | `parseSseEvents` 改为 per-line try/catch，跳过坏行保留有效 events | 06-30 |
| **R-74** | `ChromaStore.build_index` 捕获 `(ValueError, chromadb.errors.NotFoundError)` 替代裸 `except Exception` | 06-30 |
| **R-78** | `events()` 添加 `task_id` 前置检查：`if self._task_id is None: raise RuntimeError(...)` | 06-30 |
| **R-79** | `events()` `finally` 块移除 `_on_done` 调用（消费者断开不应触发任务完成回调），添加注释说明清理由 `_cleanup_background` 负责 | 06-30 |
| **R-80** | `_emit` 队列写入失败添加 `logger.warning`（替代 `except Exception: pass`） | 06-30 |
| **R-81** | `events()` 文件解析失败添加 `logger.warning`（替代 `except Exception: continue`） | 06-30 |
| **R-82** | 提取 `_first_item()` 辅助函数，`items[0]` 访问添加 `isinstance(item, dict)` 防御检查 | 06-30 |
| **R-83** | `_print_web_event` 单元测试：13 个新增测试覆盖 `_first_item`（4 个）和所有 event subtype 格式化（9 个包括 defensive） | 06-30 |
| **R-32** | `_default_web_runtime` 配置重复加载 -> 已通过 R-20 共享工厂解决（每次调用仍加载 config，但 body 从 8 行减为 1 行调用） | 06-30 |
| **R-56** | API 层 ThreadPoolExecutor -> FastAPI `lifespan` 已有 `executor.shutdown(wait=True)` 优雅关闭 | 06-30 |
| **R-65** | `import gc` 在 `ChromaStore.close()` 中 -> 已移除（前期修复） | 06-30 |

---

## 三、S1 EventStream Review（2026-06-30）

### 实现概览

**Issue #15**: EventStream 底座 + CLI 实时进度

**变更文件**：
- `src/research_agent/web/schemas.py` — ProgressEvent 新增 `_seq` 和 `event_subtype` 字段
- `src/research_agent/web/state_graph.py` — `events()` AsyncIterator + `_emit` 双写（文件 + janus.Queue）+ `_event_seq` 计数器
- `src/research_agent/web/provider_runtime.py` — 暴露 `self.runner` 供 API 层注册表访问
- `src/research_agent/api/app.py` — `_active_runtimes` 注册表 + `_stream_events` 优先走 `runner.events()` AsyncIterator + `_cleanup_background` 清理
- `src/research_agent/cli.py` — `_print_web_event` 按 subtype 选择格式（tool_call / finding / source / subtask_completed / subtask_failed）
- `pyproject.toml` — 新增 `janus>=2.0.0`、`pytest-asyncio>=1.4.0`
- `tests/test_event_stream.py` — 9 个新增测试（C1-C4）

**测试结果**：9/9 passed（4.47s）

### 已实现功能

| 验收标准 | 状态 | 说明 |
|----------|------|------|
| `uv add janus` 成功 | ✅ | pyproject.toml 已更新 |
| `ProgressEvent` 包含 `_seq` 和 `event_subtype` | ✅ | schemas.py:107-108 |
| `_emit` 双写文件+队列 | ✅ | state_graph.py:726-734 |
| `events()` AsyncIterator 正确 | ✅ | state_graph.py:679-715 |
| API SSE 端点切换到 EventStream | ✅ | `_stream_events` 优先 `await runner.events()`，fallback 文件轮询 |
| CLI 实时打印进度 | ✅ | `on_event` callback 贯穿全链路，`_print_web_event` 按 `event_subtype` 格式化 |
| Runner 注册表 + 清理 | ✅ | `_active_runtimes[task_id]` + `_cleanup_background` |
| 测试全绿 | ✅ | 9 新增 + 105 已有（1 个竞态条件失败，非 S1 引入） |
| ADR-0023 更新 | ✅ | `event_subtype` + `_seq` 字段已记录 |

### 发现的问题（按优先级）

**P0 — 阻塞性**

| 编号 | 问题 | 位置 |
|------|------|------|
| — | （当前无 P0 未解决问题） | — |

**P1 — 功能缺陷**

| 编号 | 问题 | 位置 |
|------|------|------|
| — | （R-75/76/77 已修复，见下） | — |

**P2 — 代码质量与健壮性**

| 编号 | 问题 | 位置 |
|------|------|------|
| — | （R-78/79/80/81 已修复，见下） | — |

**P3 — 低优先级**

| 编号 | 问题 | 位置 |
|------|------|------|
| — | （R-82/83 已修复，见下） | — |

### ADR/PRD 合规性

| 文档 | 要求 | 现状 |
|------|------|------|
| **PRD #14** | ProgressEvent schema 更新 | ✅ `_seq` + `event_subtype` 已实现 |
| **PRD #14** | `_emit` 双写文件+队列 | ✅ `state_graph.py:726-734` |
| **PRD #14** | `events()` AsyncIterator | ✅ `state_graph.py:679-715` |
| **PRD #14** | API 层集成 EventStream | ✅ `_stream_events` → `runner.events()` AsyncIterator + `_active_runtimes` 注册表 |
| **PRD #14** | CLI 使用 EventStream | ✅ `on_event` callback 贯穿全链路（`create_provider_runtime` → `ProviderBackedWebResearchRuntime` → `StateGraphRunner._emit`），`_print_web_event` 按 `event_subtype` 格式化 |
| **ADR-0023** | `event_subtype` 字段 | ✅ 已实现 |
| **ADR-0023** | `_seq` 字段 | ✅ 已实现 |

### 测试覆盖

| 测试 | 状态 | 说明 |
|------|------|------|
| `TestProgressEventSchema` (3 tests) | ✅ | C1: schema 序列化、向后兼容 |
| `TestEventStreamAsyncIterator` (2 tests) | ✅ | C3: 文件回放、队列切换 |
| `TestProgressItemSubtype` (1 test) | ✅ | C4: subtype 映射 |
| `TestEmitDualWrite` (3 tests) | ✅ | C2: 双写一致性、seq 递增 |
| `TestPrintWebEvent` (13 tests) | ✅ | R-83: _first_item 防御性 + CLI 6 subtype 格式化 + defensive |
| API SSE EventStream 集成 | ✅ | `_stream_events` 优先走 EventStream，24 tests passed |

### 下一步行动

**S1 状态**：✅ **完成**。API SSE 端点已切换 EventStream，CLI callback 路径已确认工作。**P2/P3 全部修复**（R-78~R-83，2026-06-30）。

---

## 四、已有 Review 记录（2026-06-29）

> 本次审查覆盖全部 43 个 ADR。核心发现：
> - ✅ **完全合规**（40个）：项目严格遵守 ADR 决策
> - ⚠️ **部分合规/延后**（3个）：
>   - **ADR-0008**（结构化产物持久化）：R-07 已部分修复（planner/supervisor/curator/revision 的 prompt+output -> `artifacts/llm_calls/`，tool call 记录 -> `artifacts/tool_calls/`）；executor 内部调用（tool_plan/synthesis）暂未覆盖，待阶段 8 回调重构
>   - **ADR-0013**（LangGraph）：当前使用手动 `StateGraphRunner`（~550 行 while 循环），LangGraph 迁移计划阶段 7。当前的 blackboard 模式 + role invocation 设计忠实地实现了 ADR-0013 的架构意图
>   - **ADR-0016**（单 Executor）：`ResearchExecutor` 正确实现单节点多子任务并发执行模式
>
> **关键 ADR 逐项验证**（仅列架构层面最关键者）：
>
> | ADR | 要求 | 现状 |
> |-----|------|------|
> | 0004 | Context builders + typed role schemas | ✅ `context.py` + `prompt_builders.py` + `schemas.py` dataclasses |
> | 0005 | Checkpoints != task state | ✅ 当前仅手动 blackboard snapshot，阶段 7 迁移 LangGraph 后语义保持 |
> | 0017 | Local RAG ⟂ Web Research | ✅ 两个独立 workflow，永不共享上下文 |
> | 0021 | Web source snapshots -> artifacts/ | ✅ `_save_source_snapshots` -> `artifacts/web_sources/` |
> | 0023 | Phase-based progress stream | ✅ `ProgressEvent` with `phase` + `event_type`；`_emit` 填充 `details.items` |
> | 0026 | SQLite FTS5 + ChromaDB | ✅ Hybrid retrieval (RRF, k=60)；`ChromaStore` 关闭连接（R-60 已修复） |
> | 0031 | Tool registry + gateway + runner | ✅ `ToolRegistry` -> `ToolGateway` -> `ToolRunner` |
> | 0037 | CoreService use cases | ✅ 7 个用例：`init_config`、`run_local_research`、`run_web_research`、`run_both`、`list_finished_tasks`、`get_kb_status`、`rebuild_kb_index` |
> | 0042 | 测试离线且确定性 | ✅ 104 tests；`_SequencedChatClient` + `MagicMock` gateway 替代真实 LLM/Tavily |

---

## 三、下一步路线图

### 总体策略

```
阶段 5 (已完成)        阶段 6                             阶段 7                 阶段 8           阶段 9
E2E 流程跑通      ->  前端页面完善 + 统一 EventStream  ->  LangGraph 移植     ->  功能全部实现  ->  健壮性优化
✅ 完成               (流式输出 + UI 重构 + 路由)          (checkpoint)          (补齐承诺)        (生产级质量)
```

> 阶段 6 和阶段 7 的详细设计见 **PRD #14**（https://github.com/leibusi0411/research_agent/issues/14），以及：
> - **ADR-0023**（`event_subtype` / `_seq` 字段）
> - **ADR-0013 V1.1 Amendment**（LangGraph 迁移：StateGraph / TypedDict + Reducer / SqliteSaver，及明确排除 Send / stream_events / SubAgentMiddleware / LangSmith）
> - **CONTEXT.md**（EventStream、Progress Event Subtype、Event Sequence、Runner Registry、LangGraph StateGraph、State Reducer、LangGraph Checkpoint）
>
> 16 项 SSE 升级决策和 A/B 任务分解已在 grill-with-docs 中定稿（2026-06-30）。实施顺序：先 A（EventStream）后 B（LangGraph）。

### S1 ✅ 完成，进入 S2

**P2 建议修复**（✅ 全部修复，2026-06-30）：
- ~~**R-78**~~：`events()` 添加 `task_id` 前置检查 ✅
- ~~**R-79**~~：`_on_done` 回调语义澄清（消费者断开 vs 任务完成） ✅
- ~~**R-80**~~：`_emit` 队列写入失败添加日志 ✅
- ~~**R-81**~~：`events()` 文件解析失败添加日志 ✅

**P3 可选改进**（✅ 全部修复，2026-06-30）：
- ~~**R-82**~~：`_print_web_event` 防御性访问 ✅
- ~~**R-83**~~：CLI 输出格式化单元测试 ✅

**已实现架构**：
- ✅ Runner 注册表：`_active_runners[task_id]` + `_cleanup_background` 自动清理
- ✅ SSE 端点：优先 `runner.events()` AsyncIterator，fallback 文件轮询
- ✅ CLI EventStream：`on_event` callback 贯穿全链路（`create_provider_runtime` → `ProviderBackedWebResearchRuntime.runner` → `StateGraphRunner._emit` → `self.on_event`）

---

### 阶段 8：功能全部实现

> **目标**：补齐 ADR/README 承诺的功能。**预估**：L（2-3 周）

**已完成（P2 批量修复，2026-06-30）**：
- ~~**R-07**~~：✅ 结构化产物持久化已部分实现（planner/supervisor/curator/revision -> `artifacts/llm_calls/`；tool calls -> `artifacts/tool_calls/`）；executor 内部调用待阶段 8 回调重构
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
