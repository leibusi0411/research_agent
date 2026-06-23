# Use unified Research Error objects

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
