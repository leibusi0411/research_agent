# 项目进展跟踪

> 最后更新：2026-06-30 | 测试：129 passed, 1 failed (pre-existing: `_TestWebRuntime` missing `.runner`) | 当前：阶段 6 ✅ 完成，阶段 7 📋 计划中
> 后端：26 passed（`test_event_stream.py`）| 前端：13 passed, TS 零错误 | 无未解决 Review Issue
>
> R = Review Issue | P = Priority（P0 阻塞 / P1 重要 / P2 改进 / P3 低优先级）

---

## 一、项目阶段与当前状态

| 阶段 | 目标 | 状态 |
|------|------|------|
| 阶段 1 | 基础设施（Config、Workspace、TaskStorage、KB Indexing） | ✅ |
| 阶段 2 | Local RAG（SQLite FTS5 检索、CLI） | ✅ |
| 阶段 3 | Web Research 骨架（Schemas、Context、ToolGateway、StateGraph、Report） | ✅ |
| 阶段 4 | Web Research 真实运行时（Prompt Builders、StateGraphRunner、ProviderRuntime） | ✅ |
| 阶段 5 | 端到端流程跑通（正确性、边界情况、锁恢复、删除 fake 代码） | ✅ |
| 阶段 6 | 前端页面完善 + 统一 EventStream（SSE 升级 + 流式输出 + 路由 + 组件拆分） | ✅ |
| 阶段 7 | 移植 LangGraph（StateGraph → LangGraph + SqliteSaver checkpoint） | 📋 计划中 |
| 阶段 8 | 功能全部实现（产物持久化、工厂重构、死代码清理） | 📋 计划中 |
| 阶段 9 | 健壮性优化（错误处理、可观测性、类型安全、lint/type-check） | 📋 计划中 |

---

## 二、阶段 6 完成总结（S1 + S2，2026-06-30）

### S1：EventStream 底座 + CLI 实时进度

**核心变更**：`schemas.py` ProgressEvent 新增 `_seq`/`event_subtype`；`state_graph.py` `events()` AsyncIterator + `_emit` 双写（janus.Queue）；`api/app.py` `_active_runtimes` 注册表 + SSE 优先走 `runner.events()`；CLI `_print_web_event` 按 subtype 格式化。

**Review 修复**：R-78~R-83（P2/P3，2026-06-30）— 防御性检查、日志完善、`_first_item` 提取、CLI 输出测试（+13 tests）。

### S2：Web UI 实时 SSE

**核心变更**（TDD，7 任务）：
- **T1 后端**：`ProgressEventType` 新增 `"task_result"`；`_curate`/`_fail`/`_persist_task` emit 该事件（+3 tests）
- **T2 前端 SSE-first**：`subscribeTaskEvents` 新增 `onResult`/`onError` 回调；移除 `waitForTerminalResult` 轮询（+6 tests）
- **T3 组件拆分 + Router**：`react-router-dom`；App.tsx → 4 页面 + 4 组件 + 1 hook
- **T4-T6 UI polish**：ConnectionBadge、PhaseIndicator、自动滚动、淡入动画
- **T7 集成验证**：TypeScript 零错误

**Review 修复**：R-84~R-91（全部，2026-06-30）— useSSE 闭包修复、组件集成、events() 哨兵机制、DetailItem 日志、ProcessView key、CSS 变量。

### 新增/变更文件一览

| 层 | 文件 | 说明 |
|----|------|------|
| 后端 | `web/schemas.py` | `ProgressEventType` 新增 `"task_result"` |
| 后端 | `web/state_graph.py` | `_curate`/`_fail` emit `task_result`；`_close_event_queue` 哨兵 |
| 后端 | `core/local_research.py` | `_persist_task` emit `task_result` |
| 前端 | `web/src/api.ts` | `subscribeTaskEvents` 重签；`ProgressEvent` 类型补 `_seq`/`event_subtype` |
| 前端 | `web/src/App.tsx` | React Router 路由；`createTaskFinisher` 去重 |
| 前端 | `web/src/main.tsx` | `<BrowserRouter>` 包裹 |
| 前端 | `web/src/pages/*.tsx` | 4 页面：Setup / Research / Tasks / Kb |
| 前端 | `web/src/components/*.tsx` | 6 组件：Sidebar / ProcessView / DetailItem / ResultView / ConnectionBadge / PhaseIndicator |
| 前端 | `web/src/hooks/useSSE.ts` | SSE 连接状态 hook |
| 前端 | `web/src/styles.css` | 动画 + 指示器 + CSS 变量 |
| 测试 | `tests/test_event_stream.py` | +4 tests（T1: 3 + R-88: 1）→ 26 total |
| 测试 | `web/tests/sse.test.ts` | +6 tests（新建） |
| 测试 | `web/tests/App.test.tsx` | +1 test（EventSource 清理）→ 6 total |

---

## 三、全部 Review Issue 状态

### 当前未解决：0

所有 R-xxx 问题均已修复。以下为按日期的汇总：

| 日期 | 批次 | 数量 | 关键项 |
|------|------|------|--------|
| 06-26 | 早期 Review | 4 | R-15~R-18（Runtime 进度、Supervisor、CLI、Schema repair） |
| 06-29 | 深度 Review | 28 | R-13/14/19/21/23/26/27/29/30/36/38/40~43/46/55/57~61/63/64/66/68~70 |
| 06-30 | P2 批量修复 | 32 | R-07/20/22/24/25/28/31~35/37/39/44/45/47~54/56/62/65/67/71~74 |
| 06-30 | S1 EventStream | 6 | R-78~R-83 |
| 06-30 | S2 Web UI | 8 | R-84~R-91 |

### R-07 备注

结构化产物持久化已部分实现（planner/supervisor/curator/revision → `artifacts/llm_calls/`，tool calls → `artifacts/tool_calls/`）。executor 内部调用（tool_plan/synthesis）的 prompt+output 持久化待阶段 8 回调重构后补充。

---

## 四、ADR 合规性摘要

全部 43 个 ADR 已审查。核心架构决策均严格遵守：

| ADR | 关键要求 | 现状 |
|-----|---------|------|
| 0004 | Context builders + typed role schemas | ✅ |
| 0013 | LangGraph StateGraph + blackboard | ⚠️ 延至阶段 7（当前手动 StateGraphRunner 忠实实现架构意图） |
| 0017 | Local RAG ⟂ Web Research | ✅ |
| 0023 | Phase-based progress stream | ✅ `event_subtype` + `_seq` |
| 0026 | SQLite FTS5 + ChromaDB hybrid | ✅ RRF 融合检索 |
| 0038 | 最小 FastAPI + SSE surface | ✅ 9 端点 |
| 0042 | 测试离线且确定性 | ✅ 129 tests |

---

## 五、下一步路线图

```
阶段 6 ✅ 完成  →  阶段 7           →  阶段 8         →  阶段 9
                  LangGraph 移植      功能全部实现      健壮性优化
                  (checkpoint)        (补齐承诺)        (生产级质量)
```

### 阶段 7：LangGraph 移植

- 将手动 `StateGraphRunner`（~550 行 while 循环）替换为 LangGraph `StateGraph`
- 使用 `TypedDict + Reducer` 管理状态、`SqliteSaver` 做 checkpoint
- 明确排除：Send / `stream_events` / SubAgentMiddleware / LangSmith

### 阶段 8：功能全部实现

- R-07 完善：executor tool_plan/synthesis prompt+output 持久化
- CLI `task show <id>`（查看单个任务详情）
- Source 快照查看器（Web UI）

### 阶段 9：健壮性优化

- 错误处理：LLM 调用重试、SIGINT 优雅退出
- 可观测性：结构化日志、LLM 耗时记录
- 性能：R-32 config 缓存
- 工程基础：mypy/pyright、ruff、API rate limit
