# Keep default tests deterministic and offline

V1 default tests should be deterministic, local, and runnable without API keys or network access.

Python uses `pytest`:

- Unit tests cover config loading and validation, path resolution, User Config defaults, Research Error mapping, schema validation, report filename slug generation, Markdown/frontmatter parsing, chunking, progress record creation, and route-guard behavior.
- Integration tests cover task storage, task directory creation, SQLite task list behavior, `events.jsonl` append/read behavior, Knowledge Base rebuild with small fixture vaults, Local RAG retrieval over fixture indexes, and Web Research graph routing with fake model and fake tool adapters.
- Web Research tests should use fake adapters by default for model outputs, search results, fetch results, PDF results, schema repair, tool failures, and report-write failures.

Web UI uses `Vitest` for UI helpers and component behavior once React exists. Playwright is reserved for critical end-to-end flows after the Web UI is implemented, such as setup, Local RAG run, Web Research run with fake backend data, task list rendering, and Knowledge Base status/rebuild interactions.

Live provider tests are not part of the default test suite. Tests that call real model providers, real search providers, or live network URLs must be behind an explicit environment flag and should be treated as manual or opt-in integration checks.

This avoids coupling normal development verification to API keys, provider availability, network reliability, changing web content, or billing.
