# Use unified Research Error objects

> 演进注记（2026-09-09，R-240）：错误码集合自本文后实际扩充：ADR-0045 增加 `task_not_found` / `invalid_task_mode` / `report_missing` / `already_deposited` 四个；其后又新增 `llm_call_failed`（已注册 errors.py:15，role_invocation.py:44 在 LLM 调用重试耗尽后抛出）与 `kb_rebuild_error`（API 层 kb rebuild 把 core 层裸字符串错误归一化为 {code, message}，app.py:394-397；本轮审查已将其补注册进 `VALID_ERROR_CODES` 白名单）。另注：原码表中 `model_error` / `search_error` / `tool_error` 当前无任何代码抛出，仅存在于白名单。错误对象形状（code + message）、CLI 渲染 `[code] message`、result.json 存 error 的契约不变。

V1 uses one minimal error object shape across CLI output, FastAPI responses, and `result.json`:

```json
{
  "code": "kb_index_stale",
  "message": "Local RAG index is stale. Run research-agent kb rebuild before local research."
}
```

The v1 error-code set is intentionally small:

- `config_missing`
- `config_invalid`
- `busy`
- `kb_index_missing`
- `kb_index_stale`
- `kb_index_building`
- `kb_index_failed`
- `model_error`
- `search_error`
- `tool_error`
- `schema_validation_failed`
- `runtime_error`
- `file_write_error`

CLI commands render the message and exit non-zero for failed tasks, busy conditions, invalid setup, index failures, runtime failures, and Web Report File write failures. FastAPI responses use the same object as the response error body. Failed task `result.json` stores the same object under `error`; Web Report File write failure is a failed Web Research task with `code: "file_write_error"`.

The implementation may keep richer internal exception classes, stack traces, provider metadata, or debug details for logs and Debug Trace, but those are not part of the default user-facing or task-history error contract.
