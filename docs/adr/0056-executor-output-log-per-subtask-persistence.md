# ADR-0056: Executor Output Log —— 子任务级持久化与重入跳过

**日期**: 2026-09-25
**状态**: ✅ 已实施
**影响范围**: `web/executor.py`, `web/graph.py`, `web/state_graph.py`

## 背景

LangGraph 的 SqliteSaver checkpoint 是**节点级**的：execute 节点要等批内全部子任务完成、结果合并进 state 并返回后才写 checkpoint。节点内部 `ThreadPoolExecutor` 并行跑最多 `max_concurrent_subtasks` 个子任务——**进程在节点中途崩溃时，已完成的子任务结果只存在于内存，checkpoint 仍指向前一个节点**。恢复或重跑时整批重来：已花的 LLM token、已执行的工具调用、已抓取的来源快照全部重复付费。

这是 TODO 中"Full task recovery from checkpoints"延期项的主要难点之一。本 ADR 落地一个**不依赖完整恢复功能**的中间加固：把子任务结果的持久化粒度从"节点返回时"提前到"每个子任务完成时"。

## 决策

### 1. Executor Output Log

`web/executor.py` 新增 `ExecutorOutputLog`：追加式 JSONL 文件，路径 `tasks/<task_id>/artifacts/executor_outputs.jsonl`，一行一个 `ExecutorOutput`（复用 schemas 的 `to_dict` 序列化、`_parse_executor_output` 反序列化）。

- **写**：`execute()` 的 `as_completed` 循环内，每个子任务结果（含 failed 终态，含线程异常兜底的 failed 输出）一拿到就 `append`——不等整批、不等节点返回。append 位于 try/except 之外且内部兜底捕获一切异常：持久化失败只降级为"无持久记录"，绝不扭曲或杀死调研结果（R-290）
- **读**：`latest_by_subtask()` 容错解析（崩溃中途的残行跳过），同一 subtask_id 多条记录时**最后一条生效**（重跑后的新结果覆盖旧结果）
- **失败语义**：append 读写的任何 OSError 只 log warning，绝不抛出——持久化失败降级为"无持久记录"，等同没有 log，不允许日志机制杀死调研任务

### 2. 重入跳过语义（防误跳的关键界定）

`execute()` 入口按指派批次分流：

- 子任务**不在** `state["executor_outputs"]`（结果从未进 Blackboard）**且** log 有其记录 → **复用**持久化结果，不重跑（崩溃恢复场景：磁盘有、状态没有）
- 子任务**已在** `state["executor_outputs"]` → **照常重跑**（正常指派场景：Supervisor 对已合并结果的重新指派是一次新的决策，如对 failed 子任务的再次尝试，不是崩溃恢复）
- 无 log（`output_log=None`）或无记录 → 现行为不变

复用的输出照常发 `subtask_completed` 进度事件（UI 观感一致），并合入节点返回值，经既有 reducer 进入 Blackboard。

### 3. 接线

- `GraphContext` 新增必填字段 `workspace: str`（state_graph 构造时传 `str(self.workspace.root)`）
- `_execute_node` 为每个任务构造 `ExecutorOutputLog.for_task(ctx.workspace, task_id)` 并传入 `ctx.executor.execute(...)`

## 已知取舍

- **checkpoint 与 log 的双份状态**：节点正常完成后，同一批结果既在 checkpoints.sqlite 也在 jsonl。接受：log 是追加式流水（含重跑历史），checkpoint 是图状态快照，语义不同；log 体积每子任务一行 JSON，可忽略
- **复用不重放工具副作用**：复用的输出里 findings/sources 直接进 Blackboard；`events.jsonl` 里的工具调用级进度事件不会补写（它们随执行产生），但 `artifacts/web_sources` 来源快照**会**照常落盘——节点层的去重集合是进程内存态，恢复进程重写快照只是冗余 IO，方向有利。接受：崩溃恢复的首要目标是保住数据与省下重跑成本，工具级事件流的缺口由日志文件本身补齐
- **"在跑中崩溃"的子任务仍会重跑**：本加固只保护"已完成未合并"的结果；崩溃瞬间在跑的子任务无法抢救（其结果本就不存在）
- 恢复入口本身（从 checkpoint 续跑 / 任务重跑按钮）不在本 ADR 范围——本 log 让任何未来入口变得便宜，触发条件仍记录在 TODO

## 影响

- 正常路径行为不变（现有全部测试不改语义通过）；新增 7 个离线确定性测试（`tests/test_executor_recovery.py`）+ 全流程集成断言
- 任何重入 execute 的机制（未来的 checkpoint 恢复、任务重跑）立即受益：只需补跑缺失的子任务
- 崩溃后 `executor_outputs.jsonl` 本身具备取证价值（能看到崩溃前哪些子任务已完成）
