# ADR vs Code Review Report

> Generated: 2026-06-24
> Scope: Full codebase cross-referenced against 43 ADRs

---

## 1. Overall Assessment

**Overall ADR compliance: ~85%** — The codebase follows the ADR architecture closely in structure, naming, and design patterns. The main gaps are in *incomplete implementations* (expected per ADR-0041 phased approach) and a few *design drift* issues.

---

## 2. ADR Compliance Matrix

| ADR | Title | Status | Notes |
|-----|-------|--------|-------|
| 0001 | Stack selection | ✅ Compliant | Python/FastAPI/React/SQLite all present |
| 0002 | Single-user local-first | ✅ Compliant | No multi-user artifacts |
| 0003 | SQLite task store + file results | ✅ Compliant | `TaskStore` + `Workspace` match spec exactly |
| 0004 | Context builders + typed schemas | ✅ Compliant | `web/context.py` + `web/schemas.py` fully implemented |
| 0005 | Separate checkpoints from task state | ⚠️ Partial | No `blackboard_snapshot.json` writing implemented yet |
| 0006 | KB read-only ingestion | ✅ Compliant | `kb.py` never modifies vault files |
| 0007 | Tavily through Search Provider interface | ✅ Compliant | `SearchProvider` protocol + `TavilySearchProvider` |
| 0008 | Persist structured artifacts | ⚠️ Partial | Task folders created, but `artifacts/web_sources/` not populated (no real executor yet) |
| 0009 | TOML config | ✅ Compliant | All sections, defaults, validation match ADR |
| 0010 | Localhost Web UI | ✅ Compliant | `vite --host 127.0.0.1`, three pages |
| 0011 | CLI streams without daemon | ✅ Compliant | CLI runs to completion, streams progress |
| 0012 | Layered package + separate web app | ✅ Compliant | `src/research_agent/{core,web,api}` + `web/` |
| 0013 | LangGraph state graph + Blackboard | ⚠️ Partial | `WebResearchState` exists but no LangGraph graph wiring |
| 0014 | Supervisor readiness + Curator schema | ✅ Compliant | Schema objects match, route guard implemented |
| 0015 | Tool Gateway | ✅ Compliant | `ToolGateway`, `ToolRegistry`, `ToolRunner` all present |
| 0016 | Single ResearchExecutor | ⚠️ Partial | No real executor; `FakeWebResearchRuntime` simulates it |
| 0017 | Separate Local RAG / Web Research modes | ✅ Compliant | Independent task modes, no cross-calls |
| 0018 | Write Web Report Files | ✅ Compliant | `web/report.py` fully implemented |
| 0019 | Markdown reports | ✅ Compliant | YAML frontmatter, slug naming, collision handling |
| 0020 | Report template | ✅ Compliant | Summary/Findings/Sources structure, no research_gaps |
| 0021 | Web Source Snapshots as artifacts | ⚠️ Partial | Directory created but no snapshot writing |
| 0022 | Prebuilt Local RAG indexes | ✅ Compliant | Missing/stale detection, explicit rebuild |
| 0023 | Phase-based progress stream | ✅ Compliant | `ProgressEvent` schema, `events.jsonl` append |
| 0024 | Global default workspace | ✅ Compliant | `Workspace` class, directory layout matches |
| 0025 | OpenAI-compatible provider only | ✅ Compliant | Only `openai_compatible` provider implemented |
| 0026 | SQLite FTS5 + vector index | ✅ Compliant | Dual index in `kb.py`, atomic rebuild |
| 0027 | httpx + trafilatura | ✅ Compliant | `HttpxHttpClient` + trafilatura extraction |
| 0028 | List finished tasks, no deletion | ✅ Compliant | No delete endpoint/command |
| 0029 | Separate result pages by mode | ✅ Compliant | `LocalResultView` + `WebResultView` in React |
| 0030 | Setup view, no settings page | ✅ Compliant | Setup form only when `configured === false` |
| 0031 | Function-call tools + Registry/Gateway/Runner | ✅ Compliant | Three tools registered, schema validation |
| 0032 | Node prompts as code constants | ⚠️ Partial | Prompt builders referenced but not yet written (no real runtime) |
| 0033 | pypdf for PDF extraction | ✅ Compliant | `pypdf.PdfReader` in `web/tools.py` |
| 0034 | Simple local IDs + UTC timestamps | ✅ Compliant | `task_id` format, `utc_now_iso()` with Z |
| 0035 | Wide per-tool engineering boundaries | ✅ Compliant | All defaults from TOML applied in `ToolRunner` |
| 0036 | Independent Local RAG / Web Research | ✅ Compliant | File-based locks per family |
| 0037 | Core Service use cases | ✅ Compliant | All 7 use cases exposed |
| 0038 | Minimal FastAPI + SSE surface | ✅ Compliant | All 10 endpoints present |
| 0039 | Unified Research Error objects | ✅ Compliant | `{code, message}` shape, 13 error codes |
| 0040 | Human-readable CLI output | ✅ Compliant | `[code] message` format, human-readable |
| 0041 | Vertical implementation phases | ✅ Compliant | Phase 1-3 complete, Phase 4 in progress |
| 0042 | Deterministic offline tests | ✅ Compliant | All tests use fakes, no network calls |
| 0043 | uv for Python, npm for Web UI | ✅ Compliant | `pyproject.toml` + `uv.lock`, `package.json` |

---

## 3. Critical Issues

### 3.1 `ProviderBackedWebResearchRuntime` is a stub (ADR-0013, 0016, 0032)

**File:** `src/research_agent/web/provider_runtime.py:41-44`

The "real" web research runtime explicitly returns failure with `"Provider-backed Web Research runtime is not complete yet."` Only the planner phase is implemented. This means:

- **No real Web Research execution** — the system can only do web research via `FakeWebResearchRuntime`
- **No LangGraph graph wiring** — ADR-0013's state graph pattern is not implemented
- **No real executor** — ADR-0016's ResearchExecutor does not exist
- **No prompt builders** — ADR-0032's `build_planner_prompt()` etc. are not written

**Impact:** Phase 4 (Real Web tools and LLM integration, per ADR-0041) is the critical next step.

### 3.2 `CoreService` uses untyped `*args, **kwargs` (ADR-0037)

**File:** `src/research_agent/core/service.py`

`run_local_research`, `run_web_research`, `get_kb_status`, `rebuild_kb_index` all use `*args: object, **kwargs: object` signatures. This:

- Violates the typed interface contract implied by ADR-0037
- Makes the API surface opaque to callers and IDE tooling
- Hides the actual parameter names and types

### 3.3 Lock file leak risk in `api/app.py` (ADR-0036)

**File:** `src/research_agent/api/app.py` — `start_local()` / `start_web()`

The lock lifecycle manually calls `lock.__enter__()` and relies on `_run_background` to call `lock.__exit__()`. If the `ThreadPoolExecutor.submit()` call itself fails (e.g., pool shutdown), the lock file is leaked permanently, blocking all future tasks of that family.

### 3.4 `local_research._retrieve_local_results` does not use vector index (ADR-0026)

**File:** `src/research_agent/core/local_research.py`

The function loads ALL rows from the SQLite chunks table into memory and uses pure term-count scoring. It does not use:
- The Chroma/vector index at all
- The FTS5 full-text index for ranking
- Any IDF or semantic similarity

This means the "Local RAG" is effectively keyword counting, not retrieval-augmented generation. For large knowledge bases, loading all chunks into memory would also be a performance problem.

---

## 4. Design Drift Issues

### 4.1 `_public_result` defined but never called

**File:** `src/research_agent/api/app.py:165`

Dead code. Either wire it into the result endpoints or remove it.

### 4.2 `_print_web_events` defined but never called

**File:** `src/research_agent/cli.py:227`

Dead code. This function reads and replays events from a JSONL file but is never invoked.

### 4.3 TOML rendering via string concatenation

**File:** `src/research_agent/core/config.py` — `_render_config_toml()`

Config is written as raw string concatenation rather than using a TOML serialization library. This is fragile — special characters in paths or values could produce invalid TOML.

### 4.4 `FakeWebResearchRuntime` hardcoded in CLI

**File:** `src/research_agent/cli.py`

The `web` and `both` commands hardcode `FakeWebResearchRuntime`. While this is appropriate for the current development phase (ADR-0041 Phase 3), the CLI should eventually use `ProviderBackedWebResearchRuntime` by default, with the fake available only through a test flag.

### 4.5 No `blackboard_snapshot.json` writing (ADR-0005)

ADR-0005 specifies that blackboard state should be persisted as a snapshot after each Supervisor decision. The `WebResearchState` class exists but no snapshot serialization or file writing is implemented.

### 4.6 No `artifacts/web_sources/` population (ADR-0021)

The workspace creates the `artifacts/web_sources/` directory, but no code writes actual source snapshots there. This requires the real ResearchExecutor (Phase 4).

---

## 5. Code Quality Issues

### 5.1 SSE polling with 30-second deadline

**File:** `src/research_agent/api/app.py` — `_stream_events()`

The SSE generator polls a JSONL file with a 30-second total deadline. If a web research task runs longer than 30 seconds (which is typical), the SSE stream will terminate prematurely. The frontend works around this with `waitForTerminalResult` polling, but the SSE stream should ideally last until the task completes.

### 5.2 No graceful shutdown for background tasks

**File:** `src/research_agent/api/app.py`

The `ThreadPoolExecutor` is not shut down on application exit. If the FastAPI process is killed, running research tasks are abandoned without cleanup (lock files remain, partial results may be written).

### 5.3 `Workspace.append_event` has no error handling

**File:** `src/research_agent/core/workspace.py`

If the task directory does not exist when `append_event` is called, it will raise an unhandled `FileNotFoundError`. The caller is expected to create the folder first, but there's no defensive check.

### 5.4 `_extract_text` for PDF silently swallows errors

**File:** `src/research_agent/core/kb.py`

When PDF extraction fails, it returns an empty string with no logging or error propagation. This could lead to silent data loss during KB rebuild.

---

## 6. Test Coverage Assessment

### 6.1 Strengths (per ADR-0042)

- **All tests are deterministic and offline** — no network calls, no API keys required
- **Fake adapters cover all major paths** — `FakeWebResearchRuntime`, `FakeChatModelClient`, `FixedEmbeddingClient`, `InMemoryHttpClient`
- **Error path coverage** — file_write_error, schema_validation_failed, kb_index_missing, kb_index_stale, busy, runtime_error all tested
- **Three test layers** — unit (pytest), component (Vitest), e2e (Playwright) all present
- **SSE parsing tested** — both Python JSONL writing and TypeScript SSE parsing covered

### 6.2 Gaps

| Gap | Impact | Recommendation |
|-----|--------|----------------|
| No `CoreService.run_both` direct unit test | Only tested via CLI subprocess | Add direct API test |
| No concurrent task execution test | Lock contention untested | Add parallel local+web test |
| No config re-init test | Overwriting existing config untested | Add re-init scenario |
| No empty query test for local research | Edge case | Add zero-result test |
| No SSE stream lifecycle test | Only checks substring content | Test full stream completion |
| No retry exhaustion test | Gateway always retries successfully | Test permanent failure after retries |
| No SIGINT/cancellation test | Graceful shutdown untested | Add interrupt handling test |

---

## 7. Recommendations (Priority Order)

### P0 — Must Fix Before Phase 4

1. **Type `CoreService` method signatures** — Replace `*args, **kwargs` with explicit typed parameters
2. **Fix lock leak in API** — Use a proper context manager or try/finally pattern
3. **Implement `ProviderBackedWebResearchRuntime`** — This is Phase 4's primary deliverable

### P1 — Should Fix Soon

4. **Wire `_public_result` or remove it** — Dead code cleanup
5. **Wire `_print_web_events` or remove it** — Dead code cleanup
6. **Use a TOML writer for config rendering** — Prevents malformed config files
7. **Add error handling for `append_event`** — Defensive programming

### P2 — Nice to Have

8. **Improve local research scoring** — Use FTS5 ranking at minimum, vector search ideally
9. **Add SSE stream lifecycle management** — Keep stream open until task completes
10. **Add graceful shutdown** — Clean up locks and background tasks on exit
11. **Log PDF extraction failures** — Don't silently swallow errors

---

## 8. Summary

The codebase is a well-structured implementation of the ADR design, with clean layering, proper use of protocols for dependency injection, comprehensive test coverage with fakes, and faithful adherence to the error model, ID format, and API surface specifications. The main gap is the incomplete Phase 4 (real Web Research runtime), which is expected per ADR-0041's phased approach. The P0 issues around type safety and lock management should be addressed before building on top of the current foundation.
