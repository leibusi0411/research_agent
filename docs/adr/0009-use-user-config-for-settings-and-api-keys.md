# Use user-level TOML config for settings and API keys

> 演进注记（2026-09-09，R-226）：下文配置形状中的 `[chat_model.local_summarizer]` 节在 v1 实际未接线：`_parse_role_chat_models`（core/config.py）的角色解析列表只有 `planner`、`executor`、`supervisor`、`curator` 四个 Web 角色，`local_summarizer` 即使写入 TOML 也不会被解析；`build_role_chat_model_config(config, "local_summarizer")`（core/service.py、api/app.py）永远静默回退到全局 `[chat_model]`，无报错。v1 有意只接线 4 个 Web 角色，local_summarizer 槽位保留但未接线（已知取舍）；如需恢复，只需在解析列表中增加一项。四个 Web 角色的 per-role 覆盖机制与字段级回退仍然成立。

> 演进注记（2026-09-09，R-227）：原文 "Existing config: prompt before overwrite" 未兑现。CLI `research-agent init` 没有覆盖提示——cli.py 直接把参数交给 `CoreService.init_config`，core/config.py 无条件 `write_text` 全量覆写已有配置。ADR-0047 只把"全量重写不提示"显式接受给 Web Settings 场景；CLI 的实际行为同样如此，此处一并承认。正文对应条目已按现实修正。

> 演进注记（2026-09-09，R-254）：配置路径解析比原文多两个机制（core/config.py `default_config_path`）：环境变量 `RESEARCH_AGENT_CONFIG_PATH` 优先覆盖；无 `APPDATA` 环境变量时（POSIX 系统）回退 `~/.config/research_agent/config.toml`。另：`max_retrieval_rounds` 与 `max_concurrent_subtasks` 实际只做 `int()` 转换，并无正数校验。正文对应条目已按现实修正。

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
- `max_retrieval_rounds`: parsed as an integer (no positivity check) and defaults to `3`.
- `max_concurrent_subtasks`: parsed as an integer (no positivity check) and defaults to `3`.
- `[web_tools]` values: use defaults when omitted and do not expose these advanced engineering boundaries in the v1 Web UI setup flow.
- Existing config: v1 overwrites an existing config in full without prompting; complex config merge is not supported.
