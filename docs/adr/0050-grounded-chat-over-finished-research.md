# ADR-0050: Grounded Chat over Finished Research Tasks

- 日期：2026-09-08（R-262）
- 状态：已接受
- 关联：ADR-0032（提示词为代码常量）、ADR-0047（常驻 Settings 页）、CONTEXT.md「TaskChatService」

## 背景

调研完成后用户经常想就报告内容追问（"这一步再展开讲讲"、"结论和我的笔记矛盾吗"）。
此前唯一的路径是再发起一次完整调研，既慢又贵。我们想要 NotebookLM 式的体验：
调研产物作为参考资料，用户勾选其中的来源，围绕它们连续问答。

## 决策

1. **轻量单角色 ChatService，不进 LangGraph 流水线。**
   新增 `research_agent.core.chat.TaskChatService`，只做"组装上下文 → 调 chat model → 落盘"。
   复用既有 `ChatModelClient.complete()` 接口（`build_role_chat_model_config(config, "chat")`，
   默认回退全局 chat model）。没有工具、没有图、没有状态机——
   对话是"检索完成后的消费行为"，不是"调研工作流"。

2. **两层记忆。**
   - 静态接地：任务 `result.json` 的 question + curator_output（summary/findings/sources），
     每次请求重新渲染进 prompt；findings 超过 24k 字符按 subtask 顺序截断。
   - 滚动历史：`tasks/{task_id}/chat.jsonl`，每轮追加 user/assistant 两行；
     历史以 `User:`/`Assistant:` 文本形式回放进 prompt（单 prompt 接口下的最简实现）。

3. **来源勾选收缩接地面（NotebookLM 式）。**
   `selected_sources`（source_id 列表）过滤注入的 sources 与 findings
   （finding 与选中集合有 `source_ids` 交集才保留）。空列表/缺省 = 全量注入。
   来源渲染为 `[S1]` 编号，系统提示要求回答按编号引用。

4. **HTTP 面：**
   - `POST /api/tasks/{task_id}/chat` `{message, selected_sources?}` → `{reply}`；
   - `GET  /api/tasks/{task_id}/chat` → `{messages}`。
   错误沿用统一形状：`config_missing`（未配置 chat model，与启动调研同语义）、
   `task_not_found`（404，任务目录不存在）、`config_invalid`（空消息）、
   `llm_call_failed`（模型调用异常包装）、`file_write_error`（chat.jsonl 写入失败）。
   只允许对 `status=completed` 的任务对话：`result.json` 在任务创建时就存在
   （status=running），因此显式检查状态，未完成任务返回 `runtime_error`。

5. **v1 非流式。** 回复一次性返回（UI 显示 "Thinking…"）。
   SSE 基础设施虽然现成，但 providers 层尚无流式接口；先落地行为，流式留作演进。

6. **前端：Research 页调研完成后出现入口。**
   `ChatPanel`（web + completed + 有 curator_output 才渲染）：中间对话卡片
   （消息流 + 底部输入栏），右侧 References 卡片（复选框，默认全选），
   勾选集合随每条消息提交。页面宽度在聊天态扩到 1060px 容纳双栏。

## 后果

- 对话历史与任务同目录（`chat.jsonl`），删除任务即连带清理，无独立存储。
- `selected_sources` 逐轮可以变化：历史回放的是对话文本，不重放当时的勾选，
  接地面永远以"当轮勾选 + 全部 findings 中匹配者"为准——简单且可预期。
- Local 任务目前没有 curator_output，聊天会得到"上下文无法回答"；把 local_results
  纳入接地面是后续演进项。
- 流式回复、对话内引用跳转、按 finding（而非 source）勾选，均为演进方向。

## 演进注记

- 2026-09-08（R-262）：初版落地。
- 2026-09-11（R-262 复审处置）：`build_role_chat_model_config(config, "chat")`
  目前总是回退全局 chat model——`config.py` 的 `_parse_role_chat_models`
  只解析 planner/executor/supervisor/curator 四角色（与 `local_summarizer`
  同现状）；要启用 per-role 覆盖需先在该解析器中登记 `chat` 角色。
  复审同时收紧：24k findings 预算对"有 sources / 无 sources"两条渲染分支
  统一生效；历史回放长度暂无上限（长对话会持续增大 prompt），加轮次上限
  或摘要压缩是演进方向。
