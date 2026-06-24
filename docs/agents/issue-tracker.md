# Issue Tracker: GitHub

Issues and PRDs for this repo live as GitHub issues in `leibusi0411/research_agent`.

Use the `gh` CLI for issue tracker operations from inside this repository.

## Conventions

- Create an issue: `gh issue create --title "..." --body-file <file> --label "ready-for-agent"`
- Read an issue: `gh issue view <number> --comments`
- List issues: `gh issue list --state open`
- Comment on an issue: `gh issue comment <number> --body "..."`
- Apply a label: `gh issue edit <number> --add-label "..."`
- Remove a label: `gh issue edit <number> --remove-label "..."`
- Close an issue: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v`; `gh` does this automatically when run inside this clone.

## When A Skill Says "Publish To The Issue Tracker"

Create a GitHub issue in `leibusi0411/research_agent`.

## When A Skill Says "Fetch The Relevant Ticket"

Run `gh issue view <number> --comments`.
