# Define node prompts as code prompt builders

V1 Web Research prompts for Planner, ResearchExecutor, Supervisor, Curator, and schema repair will be defined as code-level prompt builder functions in a prompts module rather than external user-editable prompt files. Builders such as `build_planner_prompt(...)`, `build_executor_prompt(...)`, `build_supervisor_prompt(...)`, and `build_curator_prompt(...)` generate prompts that instruct the model to return JSON matching the relevant output schema without Markdown; schema repair remains a one-time fallback LLM call after parsing or validation failure, not an additional LangGraph node.

Planner prompts ask for `research_title` and subtask question drafts only. They must not ask the model to produce `subtask_id`, `status`, or `goal`; runtime normalization assigns stable subtask IDs and initial `pending` status.

Initial Planner prompts ask for 3-5 subtask drafts. Plan Revision prompts ask for 1-3 new subtask drafts to append to the existing plan. These counts guide model output but are not separate runtime hard limits.
