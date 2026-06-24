# Agent Rules

- 每实现一个功能后，必须使用 subagent review，并通过单元测试、集成测试和 e2e 测试；只有这些全部通过，才算该功能通过。

## Agent skills

### Issue tracker

Issues and PRDs are tracked in GitHub Issues for `leibusi0411/research_agent`. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default five-label triage vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This repo uses a single-context domain documentation layout with root `CONTEXT.md` and ADRs under `docs/adr/`. See `docs/agents/domain.md`.
