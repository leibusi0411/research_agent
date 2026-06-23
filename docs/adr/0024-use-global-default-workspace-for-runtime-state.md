# Use a global default workspace for runtime state

Research Agent will use a global configuration value for the default workspace, and CLI/Web UI runs from other directories will still store task history, Knowledge Base indexes, internal task artifacts, Web source snapshots, and Web Report Files under that workspace. This avoids scattering runtime state across launch directories and keeps the Markdown Vault separate from application-managed state.

The shell launch directory is not the runtime state root. Commands can be started from any directory, but task data, indexes, reports, and logs are always written under `config.workspace.default_workspace`. The launch cwd is used only to resolve user-entered relative paths during setup before writing absolute paths into User Config.

V1 uses this workspace layout:

```text
{default_workspace}/
  tasks/
    {task_id}/
      task.json
      events.jsonl
      result.json
      artifacts/
        web_sources/
  indexes/
    local/
      fts.sqlite
      chroma/
      manifest.json
  reports/
    web/
      {topic_slug}-{yyyy-mm-dd}.md
  logs/
```

`tasks/` stores task metadata, progress records, result-display data, and mode-specific artifacts; `indexes/local/` stores rebuildable Local RAG indexes; `reports/web/` stores local Markdown Web Report Files; and `logs/` is reserved for application logs. Task artifact directory names use the task ID format `task_yyyymmdd_hhmmss_<random6>`, for example `task_20260623_103000_a1b2c3`.
