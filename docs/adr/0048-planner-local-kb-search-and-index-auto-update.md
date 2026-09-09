# ADR-0048: Planner 本地知识调研（local_kb_search）与索引自动增量更新

**日期**: 2026-09-09
**状态**: ✅ 已实施
**影响范围**: `core/kb.py`, `core/chroma_store.py`, `core/service.py`, `web/graph.py`, `web/prompt_builders.py`, `web/state_graph.py`

## 背景

ADR-0046 让 Planner 在规划前获得一次 Prior Knowledge 注入（按原始问题自动检索 top-5），但这个"种子"有两个局限：① 查询词固定为原始问题，覆盖面窄；② 计划修订时认知已更新，本地视角却不会刷新。TODO.md 中 "Local KB as a Web Research tool (`local_kb_search`)" 记录了将本地检索开放给调研流程的设想，并注明触发条件（deposit 使 vault 增长到初始切片明显不足，或 Planner 表现出未利用本地知识）。用户确认触发，并明确了方向：**本地知识归规划、网络证据归执行**——Planner 主动查本地来塑形计划，Executor 保持纯 Web 工具循环。

同时，deposit 使索引变 stale 后必须手动 `kb rebuild` 的体验较差（TODO: "Automatic or one-click index refresh" / "Incremental index update command"）。本 ADR 一并落地增量更新。

## 决策

### 1. Planner 本地知识调研（local_kb_search）

`web_planning` 节点在正式规划调用前插入一个**有界的本地调研阶段**，与 Executor 的"规划工具调用 → 执行 → 综合"三段式对称：

1. **查询优化**（LLM 调用）：Planner 基于原始问题 + Prior Knowledge 种子，生成最多 **3 个**定向查询词（JSON `{"queries": [...]}`，允许为空——本地库不相关时跳过）
2. **并行检索**：每个查询词调用只读混合检索（FTS5 + 向量 + RRF，即 `retrieve_local_chunks`，与独立 Local RAG 完全同源），通过 `ThreadPoolExecutor` 并行执行
3. **合并**：按 (source_path, text) 去重，多查询命中加权排序（每条文本截断至 800 字符；总量有界于 3×top_k）
4. **正式规划**（LLM 调用）：规划提示词新增"本地知识参考（可能不完整——仅供参考）"区块

检索结果**不包含 LLM 总结**（工具只封装检索段）；查询结果只进 Planner 的提示词切片，不写进 findings/sources——本地文件路径与网络 URL 的溯源口径不混。

### 2. 边界的重新表述（演进 ADR-0046/0017 的边界语义）

Research Workflow Boundary 从"Web 任务不接触本地知识"细化为**按角色划分**：

- **Planner**：可读本地知识库（Prior Knowledge 种子 + `local_kb_search` 定向调研），用于塑形计划
- **Executor**：只使用 Web 工具（注册表不变，`local_kb_search` 不注册进共享 ToolRegistry——Executor 提示词由注册表动态生成，注册即泄漏）
- **Supervisor / Curator**：不接触本地知识（Curator 报告不含本地路径，溯源口径不混）
- 独立 Local RAG 任务语义不变（ADR-0022 的 `ready` 门槛仍适用）

### 3. 索引自动增量更新（两层确定性钩子，非工具）

新增 `KnowledgeBaseIndex.update(max_files=...)`：就地增量刷新——仅对新增/修改/删除的文件重切块、重嵌入，未变更文件保留原 chunk；FTS5 事务内更新，Chroma 失败不回滚 FTS5（对齐 rebuild 语义）；变更数超过 `max_files` 时跳过并保持 stale（防止意外批量重嵌入）。

- **Deposit 触发**：deposit 写入报告后自动调用 `update_kb_index(max_files=5)`（确定性系统行为，非工具——触发点明确、成本极小、只有一篇确定变更），失败不影响 deposit 本身
- **调研前触发**：Planner 本地调研前，若索引 stale 且变更数 ≤ 10（`build_index_auto_updater`，上限写死为代码常量）则先增量更新再检索；变更过大则保持 stale 降级
- **刻意不做**：全量 rebuild 不作为 agent 工具暴露（昂贵写操作 + 并发风险，保留为用户显式动作）；增量更新也不注册为工具（有确定性正确答案的决策写成代码，不交给模型判断）

## 影响

- Web Research 规划成本：每次规划/修订 +1 次小 LLM 调用 + ≤3 次本地检索（~1 秒）
- 提示词：`build_planner_prompt` 新增 `local_survey` 参数与"仅供参考"区块；新增 `build_planner_survey_prompt`
- 降级矩阵：索引 missing/failed/building 或关闭注入 → 跳过调研（不发 LLM 调用）；stale → 调研旧索引（结果标注可能不完整）；stale + 变更小 → 先增量更新；调研 LLM 失败 → 吞掉并继续（辅助阶段不允许杀死规划）
- 测试：`tests/test_kb_index.py` +4（增量更新/无变更 no-op/超限跳过/缺索引跳过）、`tests/test_kb_deposit.py` +2（deposit 触发/离线跳过）、`tests/test_planner_survey.py` +6（问卷提示词/节点编排/并行检索/降级/自动更新）
