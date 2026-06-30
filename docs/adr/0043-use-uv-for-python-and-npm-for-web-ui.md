# Use uv for Python and npm for Web UI

V1 uses `uv` and `pyproject.toml` for the Python package, CLI, and backend dependencies. The Python package lives under `src/research_agent/`, with tests under `tests/`.

Common Python commands:

```text
uv run pytest
uv run research-agent ...
```

The Web UI lives under `web/` and uses npm with Vite, React, and TypeScript. V1 does not need pnpm, Poetry, a monorepo build system, Turborepo, or a checked-in project config example.

Common Web UI commands:

```text
cd web
npm run dev         # Vite dev server (frontend only, needs backend on :8001)
npm run dev:all     # concurrently starts backend :8001 + frontend :5173
npm run build       # production build → dist/
npm test            # Vitest unit tests
```

This keeps the Python backend and React frontend separated while avoiding extra workspace tooling before the product boundaries are implemented.
