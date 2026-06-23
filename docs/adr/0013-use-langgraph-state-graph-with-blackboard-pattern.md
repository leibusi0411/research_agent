# Use a LangGraph state graph with a Blackboard pattern for Web Research

The Web Research workflow is a state graph rather than a one-way pipeline: Planner creates or revises plans, Executor Nodes gather sources and findings, Supervisor routes between further execution, plan revision, curation, or stopping, and Curator drafts the Research Output from the Blackboard. These roles coordinate through Research Task State as a Blackboard instead of direct agent-to-agent chat, making Web Research recoverable, auditable, and easier to test; Local RAG remains a retrieval display flow rather than a state-graph research workflow in v1.

The graph follows `SupervisorOutput.route` for routing. `SupervisorOutput.saturation` records the Supervisor's research-saturation judgment for explanation and auditing, but it is not itself a graph edge selector.

The graph applies a runtime route guard after SupervisorOutput and before executing the next edge. If Supervisor returns `continue_execution` but `max_retrieval_rounds` has already been reached, runtime must not route back to ResearchExecutor. It redirects to `curate` when the Blackboard has usable findings and sources, or to `fail` when it does not. This keeps hard iteration limits out of the Supervisor prompt while preventing execution loops.
