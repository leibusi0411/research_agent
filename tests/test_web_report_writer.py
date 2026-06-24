from pathlib import Path

from research_agent.core.workspace import Workspace
from research_agent.web.report import render_web_report, slugify_report_topic, write_web_report
from research_agent.web.schemas import CuratorOutput, Finding, WebSource


def curator_output() -> CuratorOutput:
    source = WebSource(source_id="src_1", title="LangGraph Docs", url="https://example.com/langgraph", fetched_at="2026-06-23T10:00:00Z")
    finding = Finding(finding_id="f_1", subtask_id="st_1", text="LangGraph supports state graphs.", source_ids=["src_1"])
    return CuratorOutput(
        title="LangGraph 深度研究: Planner/Executor?",
        summary="A concise summary.",
        findings=[finding],
        sources=[source],
    )


def test_slugify_preserves_chinese_and_removes_windows_illegal_chars():
    slug = slugify_report_topic("LangGraph 深度研究: Planner/Executor? *Draft*")

    assert slug == "langgraph-深度研究-plannerexecutor-draft"
    assert len(slug) <= 80


def test_render_web_report_template_excludes_research_gaps():
    markdown = render_web_report(
        task_id="task_20260623_103000_a1b2c3",
        created_at="2026-06-23T10:30:00Z",
        output=curator_output(),
    )

    assert "title: \"LangGraph 深度研究: Planner/Executor?\"" in markdown
    assert "task_id: \"task_20260623_103000_a1b2c3\"" in markdown
    assert "## Summary" in markdown
    assert "A concise summary." in markdown
    assert "## Findings" in markdown
    assert "LangGraph supports state graphs. [1]" in markdown
    assert "## Sources" in markdown
    assert "1. LangGraph Docs - https://example.com/langgraph" in markdown
    assert "research_gaps" not in markdown


def test_render_web_report_sanitizes_frontmatter_newlines():
    output = curator_output()
    output = CuratorOutput(
        title="Title\nmalicious: true",
        summary=output.summary,
        findings=output.findings,
        sources=output.sources,
    )

    markdown = render_web_report(
        task_id="task_20260623_103000_a1b2c3",
        created_at="2026-06-23T10:30:00Z",
        output=output,
    )

    frontmatter = markdown.split("---", 2)[1]
    assert "\nmalicious: true" not in frontmatter
    assert 'title: "Title malicious: true"' in frontmatter


def test_write_web_report_uses_topic_date_and_collision_suffix(tmp_path):
    workspace = Workspace(tmp_path)
    first = write_web_report(
        workspace=workspace,
        task_id="task_20260623_103000_a1b2c3",
        created_at="2026-06-23T10:30:00Z",
        output=curator_output(),
    )
    second = write_web_report(
        workspace=workspace,
        task_id="task_20260623_104000_d4e5f6",
        created_at="2026-06-23T10:40:00Z",
        output=curator_output(),
    )

    assert first.name == "langgraph-深度研究-plannerexecutor-2026-06-23.md"
    assert second.name == "langgraph-深度研究-plannerexecutor-2026-06-23-2.md"
    assert first.read_text(encoding="utf-8").startswith("---")
    assert second.is_file()


def test_write_web_report_failure_is_raised_as_file_write_error(tmp_path):
    workspace = Workspace(tmp_path / "runtime")
    blocking_file = workspace.root / "reports"
    blocking_file.parent.mkdir(parents=True, exist_ok=True)
    blocking_file.write_text("not a directory", encoding="utf-8")

    try:
        write_web_report(
            workspace=workspace,
            task_id="task_20260623_103000_a1b2c3",
            created_at="2026-06-23T10:30:00Z",
            output=curator_output(),
        )
    except Exception as exc:
        assert getattr(exc, "code", None) == "file_write_error"
    else:
        raise AssertionError("Expected file_write_error")
