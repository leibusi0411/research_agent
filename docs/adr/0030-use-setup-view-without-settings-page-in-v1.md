# Use setup view without a Settings page in v1

V1 Web UI will not include a general Settings page. Configuration is managed through `research-agent init` and `%APPDATA%/research_agent/config.toml`, while the Web UI only shows a setup view when User Config is missing. The setup flow mirrors `research-agent init`: it writes required configuration only and does not scan the Knowledge Base, build indexes, start research, or call providers during setup.
