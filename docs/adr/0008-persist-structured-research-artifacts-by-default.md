# Persist structured research artifacts by default

Task History will persist structured role inputs and outputs, tool calls, sources, findings with `source_ids`, saturation checks, plan revisions, errors, subtask status, failure reasons, and model usage metadata when available. It will not store full prompts, full model completions, hidden reasoning, provider raw responses, or the complete Executor Scratchpad by default; fuller runtime details require an explicit Debug Trace mode.
