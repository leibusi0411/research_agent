# ADR-0054: Curator 按子任务分章节的结构化调研报告

- 日期：2026-09-18（R-277）
- 状态：已接受
- 关联：ADR-0020（报告模板，见其演进注记）、ADR-0032（提示词为代码常量）、ADR-0050（对话接地）、CONTEXT.md「Curator」「CuratorOutput」

## 背景

Curator 原先只产出一段 `summary`（"Create a concise title and summary"），
报告文件与 Web Report 卡片因此只有"Summary + Findings 列表"两个区块，
信息密度低、可读性差。用户要求对齐 NotebookLM / Gemini Deep Research
的报告形态：一次调研生成一份完整结构化报告，**按调研子任务分章节**。

## 决策

1. **`CuratorOutput.sections: list[ReportSection]`（heading + text）。**
   每个子任务一章、按计划顺序排列；heading 是从子任务问题蒸馏的短标题
   （不是裸 `subtask_id`）；text 是 1-3 段综合该子任务 findings 的成文
   论述（禁止要点列表），行内引用 `[f_1]` / `[src_1]`。没有 findings 的
   子任务并入末尾 "Gaps & open questions" 章，不许编造内容。
   `summary` 保留为 2-4 句导语（直接回答研究问题），兼容对话接地与旧任务。

2. **Curator 上下文与提示词。**
   `CuratorInput` 新增 `subtasks`（build_curator_context 从 state 取），
   提示词渲染"Research subtasks"清单（每行含 findings 计数），指引
   "one section per subtask, in plan order"。反幻觉规则显式化：summary 与
   sections 的每个论断必须可溯源到至少一条 finding/source，证据冲突或
   不足要明说。

3. **全链路消费（有 sections 用 sections，无则回退旧形态）：**
   - 报告文件（report.py）：Summary 之后按章渲染 `## heading`；
   - Web Report 卡片（ResultView）：Summary 之后渲染章节区
     （`.report-section`）；
   - 对话接地（chat.py）：`Report — {heading}: {text}` 注入接地面，
     预算为 findings 预算的一半（两者独立封顶、最坏情况叠加至 ~36k 字符）；**勾选来源过滤不裁剪 sections**——
     章节回答的是子任务而非单一来源，findings 已按勾选过滤，sections
     保留全量。

4. **schema/校验**：`_CURATOR_SCHEMA` 增加 sections 数组（heading/text
   必填字符串）；`_validate_curator_payload` 校验形状。旧任务的
   result.json 无 sections 键 → 各消费端回退，行为不变。

## 后果

- Curator 单次输出显著变长（token 成本上升）；上限由 chat model 的
  max_tokens（16384）约束，超限会被既有 finish_reason=length 报错捕获。
- 语义变化仅限"报告形态"；findings/sources 的数据契约不变，
  deposit、任务历史、对话勾选均不受影响。
- 子任务数量多的调研（>6 章）可能触及输出长度上限——届时考虑
  分章多次调用或压缩，为演进方向。

## 演进注记

- 2026-09-18（R-277）：初版落地。
