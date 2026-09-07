# ADR-0046: Web Research Planner 注入本地知识（Prior Knowledge）

**日期**: 2026-09-06  
**状态**: ✅ 已实施  
**影响范围**: `web/schemas.py`, `web/context.py`, `web/prompt_builders.py`, `web/state_graph.py`, `core/service.py`, `core/config.py`, `core/local_research.py`

## 背景

ADR-0017 与 ADR-0036 规定 Local RAG 与 Web Research 完全独立："Web Research does not read Local RAG indexes or Local Results"。ADR-0045 的 Knowledge Deposit 打通了 Web → Local 的沉淀方向后，反向联动成为自然下一步：Planner 做计划时看不到本地已有知识，会对知识库早已覆盖的内容重复发起网络调研，浪费搜索配额且报告增量价值低。

## 决策

**本 ADR 显式演进 ADR-0017/ADR-0036 的边界**：Web Research 在**启动前**对本地知识库做一次只读混合检索（复用 Local RAG 的 FTS5 + ChromaDB + RRF），把结果作为 **Prior Knowledge** 注入初始 state（`prior_knowledge` 字段），Planner 的初始 prompt 携带该切片，被指示"本地已覆盖的不要重复调研，子任务瞄准缺口"。

### 关键设计选择

- **只读、一次性、单向**：检索发生在图启动前，写入初始 state 后不再变化；Executor/Supervisor/Curator 的上下文切片不变。Web Research 仍不调用 Local RAG 的运行时流程，只读其派生索引。
- **可配置**：`[research] inject_local_context = true`（默认开）。关闭则完全不检索，回到 ADR-0017 的纯独立行为。
- **优雅降级**：索引 missing/building/failed 时不注入（装配层返回 `None`）；检索抛异常时 runner 记日志并继续（Web Research 不因本地索引问题失败）；无 embedding client（离线）时退化为 FTS5-only。
- **接缝**：`RunnerConfig.local_retriever` 是一个 `Callable[[question], list[PriorKnowledgeChunk]]`，由 `service.build_local_retriever` 装配；runner 不直接依赖 KB 模块，测试注入 lambda 即可。
- **prompt 有界**：最多 5 个 chunk、每个截断 800 字符。

### 不做的事

- Executor 不获得 `local_kb_search` 工具（方案 3，留待将来）；Supervisor 不看本地覆盖度（方案 4）；Curator 报告不混入 Local Results。

## 影响

- 新增 `PriorKnowledgeChunk`（text / source_path / heading_path）与 state 字段 `prior_knowledge`。
- `local_research._retrieve_hybrid` 公开化为 `retrieve_local_chunks`（两个工作流共享的检索接缝）。
- 检索结果非空时，Web Research 启动会多一条 `web_planning` progress 事件（"Found N relevant local notes."，`event_subtype="source"`）。
- CONTEXT.md 的 Planner / Research Workflow Boundary / Web Research Workflow 条目相应修订；TODO.md 的 "Local-aware Planner" 延期项部分兑现。
