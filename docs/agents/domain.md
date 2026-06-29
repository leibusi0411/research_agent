# Domain Docs

This repository uses a single-context domain documentation layout.

## Before Exploring

Read these files when they are relevant to the task:

- `CONTEXT.md` at the repo root for domain language and project boundaries.
- `docs/adr/` for architecture decision records that affect the area being changed.
- `TODO.md` for capabilities that were discussed but intentionally deferred from v1.
- GitHub Issue #1, `PRD: Research Agent V1`, for the current v1 product requirements.

If a file is missing, proceed silently instead of creating it preemptively.

## Layout

```text
/
  CONTEXT.md
  TODO.md
  docs/
    adr/
```

## Vocabulary Rule

When output names a domain concept, use the term as defined in `CONTEXT.md`. Avoid drifting to synonyms that the glossary explicitly rejects.

## ADR Conflict Rule

If a proposed change contradicts an existing ADR, surface that conflict explicitly instead of silently overriding the decision.
