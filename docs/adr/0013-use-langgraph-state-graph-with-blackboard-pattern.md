# Use a LangGraph state graph with a Blackboard pattern for Web Research

> 演进注记（2026-09-09，R-251）：route guard（`graph.py` 的 `_route_after_supervise`）实际规则超出正文描述——除 "`continue_execution` 超轮次 → curate/fail" 外还有三条未注记规则：(a) `revise_plan` 在轮次耗尽时同样被拦截转 curate/fail；(b) `last_sup` 为 `None`（无 Supervisor 输出）→ curate/fail；(c) `continue_execution` 但 `next_subtask_ids` 为空 → curate/fail（对应 REVIEW_TRACKER R-120）。另外 `recursion_limit` 并非简单等于 `max_retrieval_rounds`，而是派生公式 `max_retrieval_rounds * 3 + 5`（`state_graph.py`）。仍然成立：硬性轮次上限不进 Supervisor prompt、由运行时强制拦截，路由整体结构与 "saturation 仅作审计不作边选择" 的决策不变。

> 演进注记（2026-09-09，R-242）：正文（含 V1.1 Amendment）中提到的 `_emit` → `janus.Queue` → `EventStream` 传输层此后已被替换为 asyncio 实现的 `Bus`（`core/bus.py`：每订阅者 `asyncio.Queue`、默认容量 1024、满则丢弃并 warning、支持从工作线程跨事件循环投递），pyproject 的 janus 依赖已移除；replay-then-live 与 seq 去重语义保留（详见 ADR-0023 的同日注记）。事件层与图层正交这一点不变。

The Web Research workflow is a state graph rather than a one-way pipeline: Planner creates or revises plans, Executor Nodes gather sources and findings, Supervisor routes between further execution, plan revision, curation, or stopping, and Curator drafts the Research Output from the Blackboard. These roles coordinate through Research Task State as a Blackboard instead of direct agent-to-agent chat, making Web Research recoverable, auditable, and easier to test; Local RAG remains a retrieval display flow rather than a state-graph research workflow in v1.

The graph follows `SupervisorOutput.route` for routing. `SupervisorOutput.saturation` records the Supervisor's research-saturation judgment for explanation and auditing, but it is not itself a graph edge selector.

The graph applies a runtime route guard after SupervisorOutput and before executing the next edge. If Supervisor returns `continue_execution` but `max_retrieval_rounds` has already been reached, runtime must not route back to ResearchExecutor. It redirects to `curate` when the Blackboard has usable findings and sources, or to `fail` when it does not. This keeps hard iteration limits out of the Supervisor prompt while preventing execution loops.

## V1.1 Amendment (2026-06-30)

The following migration decisions were made during the grill-with-docs SSE + LangGraph design session:

### Included in the migration

| Scope | Decision | Rationale |
|-------|----------|-----------|
| **StateGraph** | Replace the manual `while` loop in `_run_graph` with LangGraph `StateGraph` + `add_conditional_edges` | Declarative routing eliminates implicit fallback logic (`_last_supervisor_route`, `_guard_route`); `max_retrieval_rounds` moves to `config.recursion_limit` |
| **TypedDict** | Convert `WebResearchState` from `@dataclass` to `TypedDict` with `Annotated` reducers | LangGraph requirement; standard reducers (`operator.add` for lists, last-write-wins for scalars) cover all fields |
| **SqliteSaver** | Replace manual `_save_blackboard_snapshot` with `langgraph-checkpoint-sqlite` `SqliteSaver` | Per-node automatic checkpointing replaces per-round manual snapshots; enables pause/resume |

### Explicitly excluded

| Scope | Rationale |
|-------|-----------|
| **LangGraph `Send` for parallel subtasks** | Current `ThreadPoolExecutor` (3 workers) inside the execute node is sufficient; per-subtask checkpoints would inflate state and add complexity without V1 benefit |
| **`stream_events` / `astream_events`** | LangGraph stream events expose raw channel updates (state diffs), not product-level progress events. The `_emit` → `janus.Queue` → `EventStream` path (built in Stage 6) is the product-level streaming layer and remains orthogonal |
| **`SubAgentMiddleware` for multi-agent** | Blackboard pattern already keeps roles isolated without direct agent-to-agent chat; sub-agent orchestration is not a V1 requirement |
| **LangSmith for visualization** | Cloud dependency contradicts local-first design; a local `execution_trace.md` (Mermaid diagram + per-step decisions) will be generated as a lightweight alternative |

### Relationship with EventStream

The EventStream layer (Stage 6A, `janus.Queue` + `seq` dedup + SSE endpoint switch) is built **before** LangGraph migration. LangGraph node functions (`plan_node`, `execute_node`, etc.) continue to call `_emit` exactly as the current `_run_graph` phases do. The two systems are orthogonal: `_emit` produces product events through the EventStream regardless of whether the graph loop is manual `while` or LangGraph `StateGraph`.

## V1.1 Migration Completed (2026-06-30)

The LangGraph migration (S5, issue #18) was completed. Key implementation details:

### State conversion
- `WebResearchState` (mutable `@dataclass`) → `WebResearchStateDict` (`TypedDict`, `total=False`)
- List fields use `Annotated[list[X], operator.add]` for append-on-return semantics
- `subtasks` uses custom `_merge_subtasks` reducer (upsert by `subtask_id`)
- Scalar fields use LangGraph's default last-write-wins
- `create_initial_state(question)` factory returns a fully initialized dict

### Graph structure
```
START → plan → execute → supervise → _route_after_supervise ─┬─ continue_execution → execute
                                                               ├─ revise_plan → plan_revision → execute
                                                               ├─ curate → curate → END
                                                               └─ fail → fail → END
```

### Checkpointing
- `SqliteSaver.from_conn_string()` with context-manager usage
- Checkpoint DB written to `{task_dir}/checkpoints.sqlite`
- `_save_blackboard_snapshot` method deleted

### Route guard
- `_guard_route` method deleted; logic moved to `_route_after_supervise(state)`
- `max_retrieval_rounds` enforced both in route function and via `config.recursion_limit` as safety net
- `route_after_supervise` extracted as standalone module-level function (not method nor closure) for testability; node functions (`_plan_node`, `_execute_node`, etc.) extracted from `build_web_research_graph` closures into module-level functions in `graph.py` (2026-07-02, R-100)

### Unchanged
- `_emit` + `janus.Queue` EventStream system (orthogonal)
- `ResearchExecutor` with `ThreadPoolExecutor` (no `Send` parallelization)
- All artifact persistence helpers (`_save_llm_call_artifact`, `_save_source_snapshots`, `_persist_result`, `_persist_failed`)
- `events()` async generator for SSE

### Test impact
- 125 non-e2e tests pass; 7 web_state_graph tests updated for TypedDict state
- `test_web_prompt_builders.py` (11 tests) updated with helper functions for dict state construction
- `test_web_e2e.py` snapshot assertion changed from `blackboard_snapshot.json` → `checkpoints.sqlite`
- `test_api_surface.py` `_TestWebRuntime` gained `runner = None` attribute
