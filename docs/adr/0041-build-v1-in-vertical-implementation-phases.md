# Build v1 in vertical implementation phases

V1 implementation should proceed through thin, verifiable vertical phases rather than building every layer in parallel.

Implementation phases:

1. Config, workspace, task storage, and CLI skeleton.
   - Implement User Config loading/initialization.
   - Resolve Default Workspace independent of launch cwd.
   - Create task IDs, task directories, SQLite task table, `events.jsonl`, and `result.json` plumbing.
   - Add CLI command skeletons and unified Research Error rendering.

2. Knowledge Base status/rebuild and Local RAG CLI.
   - Implement read-only ingestion for configured local sources.
   - Build SQLite FTS5 and Chroma indexes.
   - Implement stale detection and atomic rebuild.
   - Implement `kb status`, `kb rebuild`, and `local` with top Local Results.

3. Web Research graph skeleton with test doubles.
   - Implement LangGraph state graph shape, Blackboard, Context Builders, typed role schemas, progress records, route guards, and report rendering.
   - Use fake model/tool adapters first so graph routing, persistence, and failure behavior can be tested deterministically.

4. Real Web tools and LLM integration.
   - Add OpenAI-compatible chat and embedding adapters.
   - Add prompt builders and one-shot schema repair.
   - Add `web.search`, `web.fetch_extract`, and `web.download_pdf` through Tool Registry, Tool Gateway, and Tool Runner.
   - Connect Web Research CLI end to end.

5. FastAPI and SSE.
   - Expose the minimal Web API surface.
   - Stream Research Progress Stream records through SSE.
   - Read current-run results and finished task summaries through Core Service use cases.

6. React Web UI.
   - Implement Setup View, Research Page, Local Result Page, Web Report Page, Tasks Page, and Knowledge Base Index Page.
   - Keep Web UI as a thin presentation layer over the Core Service API.

Each phase should include focused tests for the behavior introduced in that phase. Later phases should not rewrite earlier product boundaries unless a design conflict is found and recorded in a new ADR.
