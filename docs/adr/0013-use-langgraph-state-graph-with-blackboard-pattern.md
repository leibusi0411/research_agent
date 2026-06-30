# Use a LangGraph state graph with a Blackboard pattern for Web Research

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

The EventStream layer (Stage 6A, `janus.Queue` + `_seq` dedup + SSE endpoint switch) is built **before** LangGraph migration. LangGraph node functions (`plan_node`, `execute_node`, etc.) continue to call `_emit` exactly as the current `_run_graph` phases do. The two systems are orthogonal: `_emit` produces product events through the EventStream regardless of whether the graph loop is manual `while` or LangGraph `StateGraph`.
