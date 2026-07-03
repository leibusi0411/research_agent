# Use user-level TOML config for settings and API keys

The v1 application will use the user-level TOML config at `%APPDATA%/research_agent/config.toml` for application settings and provider API keys, including the global default workspace, Knowledge Base path, retrieval limits, maximum concurrent subtasks, chat model provider/model/base URL/API key, embedding model provider/model/base URL/API key, search provider/API key, index backend, and advanced `[web_tools]` engineering boundaries. The project does not need a checked-in `research_agent.toml.example`, and missing config requires an explicit initialization flow such as `research-agent init` or Web UI setup.

`research-agent init` is a configuration initializer only. It collects and validates settings, creates the Default Workspace when needed, writes the user config, and exits. It resolves any user-entered relative paths against the launch cwd before saving absolute paths. It does not scan the Knowledge Base, build or update indexes, start the Web UI, start a background service, call LLM/search providers, or run a test research task. Indexing remains an explicit Knowledge Base Index action, and research remains an explicit `local`, `web`, or CLI convenience `both` command.

V1 uses this config shape:

```toml
[workspace]
default_workspace = "D:/ResearchAgent"
knowledge_base_path = "D:/ObsidianVault"

[research]
max_retrieval_rounds = 3
max_concurrent_subtasks = 3

[chat_model]
provider = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "..."
model = "gpt-4.1"

[chat_model.planner]
# Optional per-role override; falls back to [chat_model] when absent

[chat_model.executor]
# Optional per-role override; falls back to [chat_model] when absent

[chat_model.supervisor]
# Optional per-role override; falls back to [chat_model] when absent

[chat_model.curator]
# Optional per-role override; falls back to [chat_model] when absent

[chat_model.local_summarizer]
# Optional per-role override for Local RAG A+G summarization (added 2026-07-03, ADR-0044)

[embedding_model]
provider = "openai_compatible"
base_url = "https://api.openai.com/v1"
api_key = "..."
model = "text-embedding-3-small"

[search]
provider = "tavily"
api_key = "..."

[index]
backend = "sqlite_fts5_chroma"

[web_tools]
request_timeout_seconds = 45
pdf_timeout_seconds = 90
max_response_bytes = 20971520
max_pdf_bytes = 104857600
search_top_k = 10
search_top_k_max = 20
tool_retries = 2
```

Per-role `[chat_model.<role>]` sections are optional. When absent, that role uses the global `[chat_model]` settings. Each per-role section may override `provider`, `base_url`, `api_key`, and `model` independently; fields not specified fall back to the global `[chat_model]` values. The v1 setup flow only collects the global chat model and does not expose per-role configuration; users may add per-role overrides by editing the TOML file manually.

`research-agent init` collects only user-specific required values: `default_workspace`, `knowledge_base_path`, chat model `base_url`, `api_key`, and `model`, embedding model `base_url`, `api_key`, and `model`, and search `api_key`. Provider fields, index backend, research defaults, and `[web_tools]` boundaries use v1 defaults unless the user later edits the TOML file manually. The Web UI setup view follows the same simplified field set and does not expose advanced `[web_tools]` or backend choices in v1.

Initialization validation rules:

- Default Workspace: create it if it does not exist.
- Knowledge Base Vault Path: require an existing directory.
- Chat and embedding `base_url`: require a valid URL.
- Chat and embedding `api_key`: require a non-empty value.
- Chat and embedding `model`: require a non-empty value.
- Search provider API key: require a non-empty value.
- `max_retrieval_rounds`: require a positive integer and default to `3`.
- `max_concurrent_subtasks`: require a positive integer and default to `3`.
- `[web_tools]` values: use defaults when omitted and do not expose these advanced engineering boundaries in the v1 Web UI setup flow.
- Existing config: prompt before overwrite; v1 does not support complex config merge.
