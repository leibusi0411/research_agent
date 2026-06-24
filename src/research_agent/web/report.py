from __future__ import annotations

import re
from pathlib import Path

from research_agent.core.errors import ResearchError
from research_agent.core.workspace import Workspace
from research_agent.web.schemas import CuratorOutput


WINDOWS_ILLEGAL = '<>:"/\\|?*'


def slugify_report_topic(topic: str) -> str:
    cleaned = topic.lower()
    cleaned = "".join("" if char in WINDOWS_ILLEGAL else char for char in cleaned)
    cleaned = re.sub(r"\s+", "-", cleaned)
    cleaned = re.sub(r"-+", "-", cleaned).strip("-._ ")
    return cleaned[:80].strip("-") or "web-report"


def render_web_report(task_id: str, created_at: str, output: CuratorOutput) -> str:
    source_numbers = {source.source_id: index for index, source in enumerate(output.sources, start=1)}
    lines = [
        "---",
        f'title: "{_escape_frontmatter(output.title)}"',
        f'task_id: "{task_id}"',
        f'created_at: "{created_at}"',
        "---",
        "",
        f"# {output.title}",
        "",
        "## Summary",
        "",
        output.summary,
        "",
        "## Findings",
        "",
    ]
    for finding in output.findings:
        refs = " ".join(f"[{source_numbers[source_id]}]" for source_id in finding.source_ids if source_id in source_numbers)
        suffix = f" {refs}" if refs else ""
        lines.append(f"- {finding.text}{suffix}")
    lines.extend(["", "## Sources", ""])
    for index, source in enumerate(output.sources, start=1):
        lines.append(f"{index}. {source.title} - {source.url}")
    lines.append("")
    return "\n".join(lines)


def write_web_report(
    *,
    workspace: Workspace,
    task_id: str,
    created_at: str,
    output: CuratorOutput,
) -> Path:
    try:
        reports_dir = workspace.web_reports_dir
        reports_dir.mkdir(parents=True, exist_ok=True)
        date = created_at[:10]
        slug = slugify_report_topic(output.title)
        path = _next_report_path(reports_dir, slug, date)
        path.write_text(render_web_report(task_id, created_at, output), encoding="utf-8")
        return path
    except OSError as exc:
        raise ResearchError(code="file_write_error", message=f"Failed to write Web Report File: {exc}") from exc


def _next_report_path(reports_dir: Path, slug: str, date: str) -> Path:
    base = reports_dir / f"{slug}-{date}.md"
    if not base.exists():
        return base
    suffix = 2
    while True:
        candidate = reports_dir / f"{slug}-{date}-{suffix}.md"
        if not candidate.exists():
            return candidate
        suffix += 1


def _escape_frontmatter(value: str) -> str:
    normalized = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.replace("\\", "\\\\").replace('"', '\\"')
