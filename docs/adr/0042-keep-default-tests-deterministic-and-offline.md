# Keep default tests deterministic and offline

> 演进注记（2026-09-09，R-241）：真实 API 测试的实际隔离机制是"无配置才 skip"，而非本文所述的显式环境旗标：9 个真实 API 测试（tests/test_api_connections.py 3 个、test_web_e2e.py 3 个、test_web_e2e_simple.py 3 个）的 skip 条件是 `load_user_config()` 失败或 key 为占位值（"test-key"）；pyproject.toml 未注册 marker、也未在 addopts 默认排除（测试文件虽标 `@pytest.mark.e2e`，但该 marker 不构成运行门槛）。后果：配置了真实 key 的机器上 `uv run pytest` 默认就会打真实 API——"默认离线"只在无配置机器上成立。离线确定性原则本身不变：无配置环境下全部测试仍确定、离线、不依赖网络与计费。

V1 default tests should be deterministic, local, and runnable without API keys or network access.

Python uses `pytest`:

- Unit tests cover config loading and validation, path resolution, User Config defaults, Research Error mapping, schema validation, report filename slug generation, Markdown/frontmatter parsing, chunking, progress record creation, and route-guard behavior.
- Integration tests cover task storage, task directory creation, SQLite task list behavior, `events.jsonl` append/read behavior, Knowledge Base rebuild with small fixture vaults, Local RAG retrieval over fixture indexes, and Web Research graph routing with fake model and fake tool adapters.
- Web Research tests should use fake adapters by default for model outputs, search results, fetch results, PDF results, schema repair, tool failures, and report-write failures.

Web UI uses `Vitest` for UI helpers and component behavior once React exists. Playwright is reserved for critical end-to-end flows after the Web UI is implemented, such as setup, Local RAG run, Web Research run with fake backend data, task list rendering, and Knowledge Base status/rebuild interactions.

Live provider tests are not part of the default test suite. Tests that call real model providers, real search providers, or live network URLs must be behind an explicit environment flag and should be treated as manual or opt-in integration checks.

This avoids coupling normal development verification to API keys, provider availability, network reliability, changing web content, or billing.
