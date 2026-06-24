# 关键问题与部分合规项

> Generated: 2026-06-24

---

## 一、关键问题（P0 — 必须在 Phase 4 前修复）

### 1. ProviderBackedWebResearchRuntime 是空壳

- **涉及 ADR：** ADR-0013（LangGraph 状态图 + Blackboard 模式）、ADR-0016（单一 ResearchExecutor）、ADR-0032（节点 Prompt 作为代码常量）
- **文件：** `src/research_agent/web/provider_runtime.py` 第 41-44 行
- **现状：** `run()` 方法在调用 planner 后直接返回失败，消息为 `"Provider-backed Web Research runtime is not complete yet."`。只有 planner 阶段实现了调用 LLM，其余全部缺失。
- **影响：**
  - 系统只能通过 `FakeWebResearchRuntime` 执行 Web Research，无法使用真实 LLM
  - ADR-0013 要求的 LangGraph 状态图（Plan → Execute → Supervise → Continue/Revise/Curate/Fail）未建立
  - ADR-0016 要求的 ResearchExecutor 节点不存在
  - ADR-0032 要求的 `build_planner_prompt()`、`build_executor_prompt()`、`build_supervisor_prompt()`、`build_curator_prompt()` 均未编写
  - ADR-0005 要求的 `blackboard_snapshot.json` 快照写入未实现
  - ADR-0021 要求的 Web Source Snapshot（`artifacts/web_sources/`）写入未实现
- **建议：** 这是 ADR-0041 Phase 4 的核心交付物。实现时应：
  1. 建立 LangGraph StateGraph，节点为 Planner / Executor / Supervisor / Curator
  2. 实现四个 Prompt Builder 函数
  3. 实现 ResearchExecutor（支持并发子任务，受 `max_concurrent_subtasks` 限制）
  4. 实现 Supervisor 路由逻辑和 Route Guard（`max_retrieval_rounds` 检查）
  5. 在每个 Supervisor 决策后写入 `blackboard_snapshot.json`
  6. 在 Executor 完成后将源文本写入 `artifacts/web_sources/`

---

### 2. CoreService 方法签名使用 `*args, **kwargs`

- **涉及 ADR：** ADR-0037（通过 Core Service 暴露能力用例）
- **文件：** `src/research_agent/core/service.py`
- **现状：** 以下方法使用 `*args: object, **kwargs: object` 签名：
  - `run_local_research(...)` — 第 36 行
  - `run_web_research(...)` — 第 42 行
  - `get_kb_status(...)` — 第 88 行
  - `rebuild_kb_index(...)` — 第 91 行
- **影响：**
  - ADR-0037 明确了 Core Service 的七个用例签名，当前实现完全不透明
  - IDE 无法提供参数补全和类型检查
  - 调用者无法从签名得知需要传入什么参数
  - 违反了 ADR-0004 要求的"显式类型 schema"
- **建议：** 替换为显式类型签名，例如：
  ```python
  def run_local_research(
      self,
      question: str,
      *,
      task_id: str | None = None,
  ) -> dict[str, Any]: ...
  ```

---

### 3. API 层锁文件泄漏风险

- **涉及 ADR：** ADR-0036（允许 Local RAG 和 Web Research 独立运行）
- **文件：** `src/research_agent/api/app.py` — `start_local()` / `start_web()`
- **现状：** 锁的生命周期管理方式为：
  1. 手动调用 `lock.__enter__()`
  2. 将任务提交到 `ThreadPoolExecutor`
  3. 依赖后台线程中的 `lock.__exit__()` 释放锁
- **影响：**
  - 如果 `ThreadPoolExecutor.submit()` 本身失败（例如线程池已关闭），锁文件永远不会被释放
  - 锁文件残留会导致该任务族（local 或 web）永久报 `busy` 错误
  - 用户必须手动删除 `locks/` 目录下的文件才能恢复
- **建议：** 使用 `try/finally` 或 `contextlib.contextmanager` 确保锁释放：
  ```python
  try:
      lock.__enter__()
      executor.submit(_run_background, lock, operation)
  except Exception:
      lock.__exit__(None, None, None)
      raise
  ```

---

### 4. Local RAG 未使用向量索引

- **涉及 ADR：** ADR-0026（SQLite FTS5 + 本地持久化向量索引）
- **文件：** `src/research_agent/core/local_research.py`
- **现状：**
  - `_retrieve_local_results()` 将 SQLite chunks 表的**全部行**加载到内存（第 82-87 行）
  - 使用纯词频计数（`_score` 函数）排序，无 IDF、无向量相似度
  - 完全没有使用 ADR-0026 建立的 Chroma 向量索引
  - 也没有使用 FTS5 全文索引进行检索或排序
- **影响：**
  - 对于大型知识库，全表加载 + Python 排序会非常慢
  - 检索质量极低：纯词频计数无法捕捉语义相似性
  - 花费力建立的向量索引完全没有被利用
- **建议：**
  1. 优先使用 FTS5 的 `MATCH` 查询进行关键词检索
  2. 使用向量索引进行语义相似度检索
  3. 合并两种检索结果（混合检索）
  4. 限制返回结果数量（top-k）

---

## 二、部分合规项（ADR 部分实现）

### 5. ADR-0005：LangGraph 检查点与 Research Task State 分离

- **要求：** 在每个 Supervisor 决策后，将 Blackboard 状态持久化为 `tasks/{task_id}/blackboard_snapshot.json`
- **快照内容：** 当前计划（含子任务状态）、已累积的 findings、source 元数据、research gaps
- **现状：** `WebResearchState` 类已存在于 `web/schemas.py`，具备 `add_planner_output()`、`merge_executor_output()`、`apply_supervisor_output()` 三个状态变更方法。但没有任何代码将状态序列化写入 `blackboard_snapshot.json`。
- **原因：** 真实的 Supervisor 节点尚未实现（依赖 Phase 4）
- **补救时机：** 实现 `ProviderBackedWebResearchRuntime` 时一并实现

---

### 6. ADR-0008：默认持久化结构化研究产物

- **要求：** Task History 持久化结构化的角色输入/输出、工具调用、sources、findings（含 `source_ids`）、saturation 检查、plan revisions、errors、子任务状态、failure reasons、模型使用元数据
- **现状：**
  - `Workspace.create_task_folder()` 创建 `task.json` 和 `result.json` ✅
  - `TaskStore.upsert_finished_task()` 写入 SQLite ✅
  - `Workspace.append_event()` 写入 `events.jsonl` ✅
  - `FakeWebResearchRuntime` 写入完整的进度事件 ✅
  - **缺失：** 真实运行时的结构化产物（tool call 记录、model usage metadata 等）未持久化，因为真实运行时不存在
- **原因：** 依赖 Phase 4 的真实 ResearchExecutor
- **补救时机：** ResearchExecutor 实现时，在每个 tool call 后记录结构化事件

---

### 7. ADR-0013：LangGraph 状态图 + Blackboard 模式

- **要求：** Web Research 是一个状态图，Planner 创建/修订计划，Executor 节点收集 sources/findings，Supervisor 路由，Curator 起草输出。角色通过 Research Task State（Blackboard）协调。
- **现状：**
  - `WebResearchState`（Blackboard）✅ — `web/schemas.py`
  - Context Builders（为每个角色提取 Blackboard 切片）✅ — `web/context.py`
  - Role Schemas（PlannerOutput、ExecutorOutput、SupervisorOutput、CuratorOutput）✅ — `web/schemas.py`
  - Route Guard（`max_retrieval_rounds` 检查）✅ — `web/fake_runtime.py` 中的 `_guard_route()`
  - **缺失：** LangGraph StateGraph 定义和节点连接
  - **缺失：** 真实的 Supervisor 路由逻辑
- **原因：** LangGraph 集成是 Phase 4 的工作
- **补救时机：** Phase 4 实现时建立完整的 StateGraph

---

### 8. ADR-0016：使用单一 ResearchExecutor

- **要求：** 一个 ResearchExecutor LangGraph 节点处理所有 Supervisor 分配的子任务。支持并发执行（受 `max_concurrent_subtasks` 限制）。每个子任务是独立的 executor agent run。
- **现状：**
  - `ResearchConfig.max_concurrent_subtasks` 已定义（默认 3）✅ — `core/config.py`
  - `FakeWebResearchRuntime._execute()` 模拟了子任务执行 ✅ — `web/fake_runtime.py`
  - **缺失：** 真实的 ResearchExecutor 实现
  - **缺失：** 子任务并发执行逻辑
  - **缺失：** 子任务隔离（独立 scratchpad、独立 tool loop）
- **原因：** 依赖 Phase 4
- **补救时机：** Phase 4 实现 ResearchExecutor 时

---

### 9. ADR-0021：将 Web Source 快照保存为内部任务产物

- **要求：** 获取的网页源文本快照保存在 `tasks/{task_id}/artifacts/web_sources/` 目录下，作为内部产物。`WebSource` 仅保留元数据（`source_id`、`title`、`url`、`fetched_at`），全文不放入 `ExecutorOutput`、Supervisor 上下文或报告正文。
- **现状：**
  - `Workspace.create_task_folder()` 创建 `artifacts/web_sources/` 目录 ✅
  - `WebSource` schema 仅含元数据字段 ✅ — `web/schemas.py`
  - **缺失：** 没有代码将提取的文本写入快照文件
- **原因：** 真实的 ResearchExecutor 不存在，无法执行实际的网页抓取和快照保存
- **补救时机：** ResearchExecutor 实现时，在 `web.fetch_extract` 和 `web.download_pdf` 工具调用后写入快照

---

### 10. ADR-0032：将节点 Prompt 定义为代码常量

- **要求：** Prompt 是代码级的 prompt builder 函数，不是外部可编辑文件。需要实现：
  - `build_planner_prompt(...)`
  - `build_executor_prompt(...)`
  - `build_supervisor_prompt(...)`
  - `build_curator_prompt(...)`
- **现状：**
  - `web/role_invocation.py` 中的 `invoke_role_json()` 提供了通用的 LLM 调用 + schema 修复机制 ✅
  - `web/context.py` 中的 Context Builders 为每个角色准备输入 ✅
  - **缺失：** 四个 Prompt Builder 函数均未编写
  - **缺失：** Prompt 中要求模型返回 JSON（不含 Markdown）的指令未编写
- **原因：** 依赖 Phase 4 的真实运行时
- **补救时机：** 实现 `ProviderBackedWebResearchRuntime` 时编写 Prompt Builder

---

## 三、修复优先级建议

| 优先级 | 编号 | 问题 | 关联阶段 |
|--------|------|------|----------|
| P0 | #1 | ProviderBackedWebResearchRuntime 是空壳 | Phase 4 核心 |
| P0 | #2 | CoreService 方法签名无类型 | 立即修复 |
| P0 | #3 | API 锁文件泄漏风险 | 立即修复 |
| P0 | #4 | Local RAG 未使用向量索引 | Phase 2 增强 |
| P1 | #5 | ADR-0005 blackboard_snapshot.json | 随 #1 一起 |
| P1 | #6 | ADR-0008 结构化产物持久化 | 随 #1 一起 |
| P1 | #7 | ADR-0013 LangGraph 状态图 | Phase 4 核心 |
| P1 | #8 | ADR-0016 ResearchExecutor | Phase 4 核心 |
| P1 | #9 | ADR-0021 Web Source 快照 | 随 #8 一起 |
| P1 | #10 | ADR-0032 Prompt Builders | 随 #1 一起 |
