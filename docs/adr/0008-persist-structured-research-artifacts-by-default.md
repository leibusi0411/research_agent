# Persist structured research artifacts by default

> 演进注记（2026-09-09，R-231）：本 ADR 的默认持久化范围在实现中被反转。现实是：`state_graph.py` 的 `_save_llm_call_artifact` 无条件把每次角色调用的完整 prompt 与完整 output 落盘为 `tasks/<task_id>/artifacts/llm_calls/NNNN_<role>_roundNN.json`（graph.py 中各角色节点直接调用，无任何开关），全代码不存在 Debug Trace mode。反转理由：完整调用记录在真实故障排查（如 REVIEW_TRACKER R-219/R-220 的 FrozenInstanceError 掩码、截断重试）中起关键作用，本地单用户场景下默认保留。正文末句已改为现实。

Task History will persist structured role inputs and outputs, tool calls, sources, findings with `source_ids`, saturation checks, plan revisions, errors, subtask status, failure reasons, and model usage metadata when available. In addition, full prompts and full model completions of every role LLM call are persisted unconditionally under `tasks/<task_id>/artifacts/llm_calls/`; hidden reasoning, provider raw responses, and the complete Executor Scratchpad are still not stored.
