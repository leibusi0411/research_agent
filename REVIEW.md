---
phase: P2-P3-refactor-review
reviewed: 2026-07-02T00:00:00Z
depth: deep
files_reviewed: 16
files_reviewed_list:
  - src/research_agent/web/graph.py
  - src/research_agent/web/state_graph.py
  - src/research_agent/api/app.py
  - src/research_agent/web/executor.py
  - src/research_agent/core/kb.py
  - src/research_agent/web/prompt_builders.py
  - src/research_agent/web/schemas.py
  - src/research_agent/core/workspace.py
  - src/research_agent/core/service.py
  - src/research_agent/core/config.py
  - src/research_agent/web/tools.py
  - src/research_agent/core/chroma_store.py
  - web/src/api.ts
  - web/src/components/ProcessView.tsx
  - web/src/components/ResultView.tsx
  - tests/test_event_stream.py
findings:
  critical: 2
  warning: 5
  info: 4
  total: 11
status: issues_found
---

# Phase P2-P3: 重构代码审查报告

**审查时间:** 2026-07-02
**审查深度:** deep（跨文件调用链追踪）
**审查文件数:** 16
**状态:** 发现问题

## 概述

本次审查覆盖了 P2/P3 质量改进的全部变更文件，包括：从 `state_graph.py` 提取出的新文件 `graph.py`、新增的 `executor.py`、以及相关的 prompt builders、schemas、API 层、前端组件和测试文件。审查追踪了跨模块的调用链，重点检查了重构引入的正确性问题、类型一致性和错误处理。

---

## Critical Issues

### CR-01: `_execute_node` 在 plan_revision 后使用过期 supervisor 的 `next_subtask_ids` 过滤子任务

**文件:** `src/research_agent/web/graph.py:182-183`
**问题:** 当 supervisor 发出 "revise_plan" 路由指令后，图流转到 `plan_revision`，然后回到 `execute`。此时 `execute_node` 仍然读取上一次 supervisor 调用产生的 `last_supervisor_output`，并依据其 `next_subtask_ids` 过滤待执行子任务。但该 `next_subtask_ids` 是为上一次 execution 轮次准备的；plan_revision 新创建的子任务可能不在其中，导致它们被错误地跳过。

具体触发条件（罕见但可能）：LLM 在 route="revise_plan" 时仍填充了 `next_subtask_ids`（虽然 prompt 指导不应如此，但模型输出不完全可控）。此时 plan_revision 之后只有这些旧 ID 对应的子任务会执行，新创建的子任务被静默忽略。

此外，第 182 行的条件 `if last_sup is not None and last_sup.next_subtask_ids:` 在 `next_subtask_ids` 为空列表 `[]` 时为 falsy，过滤被跳过，所有 pending 子任务都会执行。对于 "revise_plan" 场景这恰好是正确的（因为 supervisor 通常在这里返回空 `next_subtask_ids`），但这依赖于模型输出而非显式意图，缺乏防御性。

**修复方案:**

```python
def _execute_node(state: WebResearchStateDict, ctx: GraphContext) -> dict[str, Any]:
    task_id = ctx.task_id
    last_sup = state.get("last_supervisor_output")
    pending = [s for s in state["subtasks"] if s.status == "pending"]

    # 仅当上一次 supervisor 路由为 "continue_execution" 且有指定
    # next_subtask_ids 时才按白名单过滤；plan_revision 后应执行所有
    # pending 子任务。
    route_history = state.get("route_history", [])
    last_supervise_step = next(
        (s for s in reversed(route_history) if s.startswith("supervise:")), None
    )
    if (
        last_sup is not None
        and last_sup.route == "continue_execution"
        and last_sup.next_subtask_ids
    ):
        pending = [s for s in pending if s.subtask_id in last_sup.next_subtask_ids]
    elif (
        last_sup is not None
        and last_sup.route != "continue_execution"
    ):
        # 非 continue_execution 路由（如 revise_plan）后不应过滤
        pass

    if not pending:
        return {
            "retrieval_round": state["retrieval_round"] + 1,
            "route_history": ["execute_round_skip"],
        }

    # ... 其余代码不变 ...
```

---

### CR-02: `_execute_node` 在无 pending 子任务时仍递增 retrieval_round，导致检索轮次硬限制被无意消耗

**文件:** `src/research_agent/web/graph.py:185-186`
**问题:** 当 `pending` 列表为空（无待执行子任务）时，`_execute_node` 返回 `{"retrieval_round": state["retrieval_round"] + 1, ...}`。这意味着检索轮次计数器因一次"空执行"而递增。如果连续发生多次空执行（例如 supervisor 路由到 continue_execution 但指定的子任务 ID 都不再 pending），硬限制 `max_retrieval_rounds` 可在没有产生任何新 evidence 的情况下被消耗完，导致 `route_after_supervise` 中的路由守卫过早强制终止任务。

**修复方案:**

```python
if not pending:
    return {
        # 不递增 retrieval_round：空执行不应消耗轮次预算
        "route_history": ["execute_round_skip"],
    }
```

如果某些调用方依赖空执行推送轮次（例如 route 守卫的递归限制），可改为对数或条件递增，但最简单的修复是**不递增**。

---

## Warnings

### WR-01: `_execute_node` 静默丢弃 executor 输出中 status_updates 为 None 的子任务

**文件:** `src/research_agent/web/graph.py:198-206`
**问题:** 当 `next()` 在 `state["subtasks"]` 中找不到某 executor 输出的 `subtask_id` 时，`original` 为 `None`，整个子任务的结果（findings、sources）不会反映在 status_updates 中，也没有任何日志警告。这可能导致数据丢失：executor 成功执行了某子任务，但其输出未被合并到状态中。

**修复方案:**

```python
original = next(
    (st for st in state["subtasks"] if st.subtask_id == output.subtask_id), None
)
if original is not None:
    status_updates.append(ResearchSubtask(
        subtask_id=output.subtask_id,
        question=original.question,
        status=output.status,
    ))
else:
    logger.warning(
        "Executor returned output for subtask %r not found in state; "
        "findings and sources will not be linked to any subtask.",
        output.subtask_id,
    )
```

---

### WR-02: `_render_step_decisions` 中 plan_revision 新子任务识别逻辑脆弱

**文件:** `src/research_agent/web/state_graph.py:136-137`
**问题:** 展示逻辑中判断哪些子任务是 "new from plan_revision" 的启发式方法：
```python
new_sts = [s for s in subtasks if s.subtask_id not in
           {eo.subtask_id for eo in executor_outputs}][-3:]
```
这段代码取"不在 executor_outputs 中的最后 3 个子任务"来代表 plan_revision 新增的子任务。但如果 executor 恰好也执行了某些 revision 中新增的子任务，它们会从列表中消失，导致显示遗漏。另外 `[-3:]` 硬编码了最多显示 3 个，但没有给出任何截断提示。

**修复方案:** 使用 `route_history` 中 plan_revision 步骤的位置信息，或直接在 `plan_revision_node` 中将新子任务 ID 列表写入 state（如 `last_revision_subtask_ids: list[str]`），然后在展示逻辑中精确引用。

---

### WR-03: `_supervise_node` 将 research_gaps 标记为 `"kind": "finding"`

**文件:** `src/research_agent/web/graph.py:251-255`
**问题:**
```python
supervisor_items: list[dict[str, Any]] = []
if supervisor_output.research_gaps:
    supervisor_items.extend(
        {"kind": "finding", "text": gap} for gap in supervisor_output.research_gaps
    )
```
Research gaps（研究缺口）被标注为 `"kind": "finding"` 传递给 progress event 消费者。这与实际 findings（研究发现）的 kind 相同，使得前端 ProcessView 无法区分两者。根据 ADR-0023，progress item 的 kind 应准确反映内容类型。

**修复方案:** 使用专用的 kind 值，如 `"kind": "research_gap"` 或复用已有的 `"kind": "finding"` 但在 UI 中附加区分标签。如果 `PROGRESS_ITEM_MESSAGES` 和 `_VALID_EVENT_SUBTYPES` 需要同步扩展，应一并更新。

---

### WR-04: `_validate_curator_payload` 和 `_validate_executor_payload` 验证不完整

**文件:** `src/research_agent/web/graph.py:52-55`、`src/research_agent/web/executor.py:36-42`
**问题:** 
- `_validate_curator_payload` 仅检查 `title` 和 `summary`，不验证 `findings` 和 `sources` 的结构。如果 LLM 返回了非法的 findings（如字符串而非对象数组），错误会延迟到 `_parse_curator_output` 的 `.get()` 调用（虽然使用默认值可以防御，但会导致空结果而没有任何提示）。
- `_validate_executor_payload` 检查 `findings` 和 `sources` 是 list 类型，但**不验证列表元素的类型**。如果 LLM 在 findings 数组中返回了字符串而非对象，`_parse_executor_output` 中 `f.get("finding_id", ...)` 会调用字符串的 `.get()` 方法，触发 `AttributeError`，导致 execption 传播到 `_execute_single` 的异常处理。

**修复方案:**

```python
def _validate_executor_payload(payload: dict[str, Any]) -> dict[str, Any]:
    check_required_field(payload, "subtask_id", str)
    if payload.get("status") not in ("completed", "failed"):
        raise ValueError("status must be 'completed' or 'failed'")
    check_required_field(payload, "findings", list, allow_empty=True)
    check_required_field(payload, "sources", list, allow_empty=True)
    # 新增：验证列表元素类型
    for i, item in enumerate(payload.get("findings", [])):
        if not isinstance(item, dict):
            raise ValueError(f"findings[{i}] must be a dict, got {type(item).__name__}")
    for i, item in enumerate(payload.get("sources", [])):
        if not isinstance(item, dict):
            raise ValueError(f"sources[{i}] must be a dict, got {type(item).__name__}")
    return payload
```

---

### WR-05: `_safe_future_result` 缺少类型注解

**文件:** `src/research_agent/core/service.py:202`
**问题:** 函数签名 `def _safe_future_result(future, family: str) -> dict:` 中 `future` 参数没有类型注解。这虽然不是运行时错误，但在重构中将函数提炼为模块级函数时，类型注解的缺失降低了代码的可读性和 IDE 支持。

**修复方案:**

```python
from concurrent.futures import Future

def _safe_future_result(future: Future, family: str) -> dict[str, Any]:
```

---

## Info

### IN-01: `_render_step_decisions` 中 plan 步骤的计数包含了所有轮次的子任务

**文件:** `src/research_agent/web/state_graph.py:99`
**问题:**
```python
lines.append(f"- **Subtasks created**: {len([s for s in subtasks if s.subtask_id.startswith('st_')])}")
```
在 "Step 1: Plan" 的展示中，这行代码统计了**所有**以 `st_` 开头的子任务（包括 plan_revision 新增的），而非仅初始规划产生的子任务。显示信息会产生误导——用户会认为初始规划创建了所有子任务。

**修复方案:** 利用 `route_history` 确定 plan_revision 发生的位置，然后仅统计在该点之前创建的子任务。或保存 `initial_plan_subtask_count` 到 state。

---

### IN-02: `_prompt_builders` 中硬编码了工具名称和描述

**文件:** `src/research_agent/web/prompt_builders.py:107-109`
**问题:** `_render_tool_plan_prompt` 中工具的名称和描述是硬编码的：
```
'1. web.search - Search the web. Arguments: {"query": "search query", "max_results": 5}\n'
'2. web.fetch_extract - Fetch and extract text from a URL. Arguments: {"url": "https://..."}\n'
'3. web.download_pdf - Download and extract text from a PDF. Arguments: {"url": "https://..."}\n'
```
如果 `ToolRegistry` 中新增或移除工具，此 prompt 模板不会自动同步，导致 LLM 可能尝试调用已不存在或名称已变更的工具。

**修复方案:** 从 `ToolRegistry` 动态生成工具列表描述，使 prompt 与注册的工具保持同步。

---

### IN-03: `_parse_user_config` 对 `web_tools` 值使用强制的 `int()` 转换

**文件:** `src/research_agent/core/config.py:198`
**问题:**
```python
web_tools=WebToolsConfig(**{key: int(value) for key, value in web_tools.items()}),
```
`int(value)` 在 TOML 值已为整数时正常工作，但如果用户手动编辑 TOML 配置并写入浮点数（如 `20971520.0`），会触发 `ValueError`，消息较不友好。虽然 `_parse_user_config` 有外层 `except (TypeError, ValueError)` 捕获，但错误消息为通用的 `"Invalid config value: {exc}"`。

**修复方案:** 对每个 web_tools 字段使用显式的 `try/except` 提供字段级别的错误消息，或使用 `round()` 容错处理。

---

### IN-04: `_execute_node` 中的 `last_sup.next_subtask_ids` 空列表检查依赖 Python 的 falsy 语义

**文件:** `src/research_agent/web/graph.py:182`
**问题:**
```python
if last_sup is not None and last_sup.next_subtask_ids:
```
空列表 `[]` 在 Python 中是 falsy，因此条件为 `False` 时过滤被跳过。虽然这在当前代码路径中恰好是正确的（plan_revision 后 supervisor 返回空 `next_subtask_ids` 时执行全部），但代码意图不清晰——读者无法区分"有意不执行过滤"和"意外跳过过滤"。

**修复方案:** 将条件改为显式检查（参见 CR-01 的修复方案），使意图明确。

---

_审查时间: 2026-07-02T00:00:00Z_
_审查者: Claude (gsd-code-reviewer)_
_深度: deep_
