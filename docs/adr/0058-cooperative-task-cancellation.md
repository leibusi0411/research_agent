# ADR-0058: Web Research 的协作式任务取消

- 日期：2026-09-21（R-286）
- 状态：已接受
- 关联：ADR-0023（进度流）、ADR-0031（family 并发锁）、ADR-0038（API 面）、CONTEXT.md「Research Progress Stream」

## 背景

调研运行中（LLM 角色调用 + 工具执行可能持续数分钟）用户没有任何中止手段，
只能等它跑完或杀掉整个后端进程。要求在 Research 页提供 Cancel 按钮。

LangGraph 的同步 `graph.invoke` 没有中途打断 API；任务跑在 uvicorn 的
线程池里，也无法安全地从另一个请求线程强杀。强杀还会留下：半写的
result.json、未释放的 family 锁、孤儿线程。

## 决策

**协作式取消（cooperative cancellation）**：

1. `StateGraphRunner.request_cancel()` 设置实例级 `threading.Event`
   （`__init__` 创建一次、`run()` 不重置——`run()` 前发出的取消必须在
   首个节点边界就生效）。
2. `GraphContext.cancel_event` 传入图；五个节点（plan / execute /
   supervise / plan_revision / curate）开头统一调用 `_check_cancelled(ctx)`，
   已取消则抛 `ResearchError(code="cancelled")`。取消最迟在**当前节点
   完成后**生效（几秒级）。
3. `_run_graph` 捕获 `code=cancelled` → 复用 `_persist_failed` 落盘
   `status="failed"` + `error={code: "cancelled", message: "Cancelled by user."}`，
   发 `task_result` 终止事件；family 锁由既有后台清理路径释放。
   **不引入独立的 "cancelled" 任务状态**——任务历史/列表/删除的既有
   语义全部复用，前端以 `error.code` 区分文案。
4. HTTP：`POST /api/tasks/{task_id}/cancel` → 从 `_active_runtimes` 找活跃
   runtime 调 `request_cancel()`；无活跃 runtime（已完成/未知任务）返回
   404 `task_not_found`。`ProviderBackedWebResearchRuntime.request_cancel`
   代理给 runner。
5. 前端：Research 页 Trace 卡运行中显示 Cancel 按钮（点击后变
   "Cancelling…"），SSE 的 `task_result` 终止帧驱动 finishTask 刷新；
   `cancelled` 任务不显示对话入口（非 completed），Tasks 页按 failed 渲染。

6. **范围**：仅 Web Research。Local RAG 是单次同步检索调用（秒级），
   无可取消窗口，不做。

## 后果

- 取消延迟 = 当前节点剩余时长（LLM 调用可能 10~30s），按钮点击后
  有 "Cancelling…" 反馈；不承诺即时终止。
- checkpointer 中可能残留中断轮次的 checkpoint——与崩溃恢复语义一致，
  不额外清理。
- `_active_runtimes` 注册表是取消的寻址机制；runtime 清理后 cancel 返回
  404，前端据此提示"任务已结束"。

## 演进注记

- 2026-09-21（R-286）：初版落地。
