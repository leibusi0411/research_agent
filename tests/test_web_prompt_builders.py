from research_agent.web.context import (
    build_curator_context,
    build_executor_context,
    build_planner_context,
    build_supervisor_context,
)
from research_agent.web.prompt_builders import (
    build_curator_prompt,
    build_executor_tool_plan_prompt,
    build_planner_prompt,
    build_supervisor_prompt,
)
from research_agent.web.schemas import (
    ExecutorOutput,
    Finding,
    PlannerOutput,
    PlannerSubtaskDraft,
    ResearchSubtask,
    SupervisorOutput,
    WebResearchStateDict,
    WebSource,
    create_initial_state,
)
from research_agent.core.errors import ResearchError


def _add_planner_output(state: WebResearchStateDict, output: PlannerOutput) -> None:
    """Simulate add_planner_output: set title and append subtasks with IDs."""
    state["research_title"] = output.research_title
    next_id = len(state["subtasks"]) + 1
    for i, draft in enumerate(output.subtasks):
        state["subtasks"] = state["subtasks"] + [
            ResearchSubtask(subtask_id=f"st_{next_id + i}", question=draft.question)
        ]


def _merge_executor_output(state: WebResearchStateDict, output: ExecutorOutput) -> None:
    """Simulate merge_executor_output: update subtask status + append findings/sources."""
    state["executor_outputs"] = state["executor_outputs"] + [output]
    # R-111: ResearchSubtask is frozen — create new objects for status changes
    updated = [
        ResearchSubtask(subtask_id=st.subtask_id, question=st.question, status=output.status)
        if st.subtask_id == output.subtask_id else st
        for st in state["subtasks"]
    ]
    state["subtasks"] = updated
    state["findings"] = state["findings"] + list(output.findings)
    state["sources"] = state["sources"] + list(output.sources)


def test_build_planner_prompt_contains_original_question():
    state = create_initial_state(original_question="What is LangGraph?")
    prompt = build_planner_prompt(state)
    assert "What is LangGraph?" in prompt
    assert "research_title" in prompt
    assert "subtasks" in prompt


def test_build_planner_prompt_for_revision_contains_existing_plan():
    state = create_initial_state(original_question="What is LangGraph?")
    _add_planner_output(state, PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Initial subtask")]))
    prompt = build_planner_prompt(state, revision=True)
    assert "Initial subtask" in prompt
    assert "revise" in prompt.lower()


def test_build_executor_tool_plan_prompt_contains_subtask_question():
    state = create_initial_state(original_question="What is LangGraph?")
    _add_planner_output(state, PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    prompt = build_executor_tool_plan_prompt(state, "st_1")
    assert "Find architecture overview." in prompt
    assert "search" in prompt.lower()
    assert "fetch" in prompt.lower()


def test_build_supervisor_prompt_contains_current_plan():
    state = create_initial_state(original_question="What is LangGraph?")
    _add_planner_output(state, PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    prompt = build_supervisor_prompt(state)
    assert "Find architecture overview." in prompt
    assert "route" in prompt.lower()


def test_build_supervisor_prompt_contains_executor_outputs():
    state = create_initial_state(original_question="What is LangGraph?")
    _add_planner_output(state, PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    source = WebSource(source_id="src_1", title="Docs", url="https://example.com", fetched_at="2026-06-23T10:00:00Z")
    finding = Finding(finding_id="f_1", subtask_id="st_1", text="LangGraph supports state graphs.", source_ids=["src_1"])
    executor_output = ExecutorOutput(subtask_id="st_1", status="completed", findings=[finding], sources=[source])
    _merge_executor_output(state, executor_output)
    prompt = build_supervisor_prompt(state)
    assert "LangGraph supports state graphs." in prompt


def test_build_curator_prompt_contains_findings():
    state = create_initial_state(original_question="What is LangGraph?")
    _add_planner_output(state, PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    source = WebSource(source_id="src_1", title="Docs", url="https://example.com", fetched_at="2026-06-23T10:00:00Z")
    finding = Finding(finding_id="f_1", subtask_id="st_1", text="LangGraph supports state graphs.", source_ids=["src_1"])
    executor_output = ExecutorOutput(subtask_id="st_1", status="completed", findings=[finding], sources=[source])
    _merge_executor_output(state, executor_output)
    prompt = build_curator_prompt(state)
    assert "LangGraph supports state graphs." in prompt
    assert "summary" in prompt.lower()
    assert "title" in prompt.lower()


def test_build_planner_prompt_for_initial_plan_requests_3_to_5_subtasks():
    state = create_initial_state(original_question="What is LangGraph?")
    prompt = build_planner_prompt(state)
    assert "3-5" in prompt or "3 to 5" in prompt


def test_build_planner_prompt_for_revision_requests_1_to_3_subtasks():
    state = create_initial_state(original_question="What is LangGraph?")
    _add_planner_output(state, PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Initial subtask")]))
    prompt = build_planner_prompt(state, revision=True)
    assert "1-3" in prompt or "1 to 3" in prompt


def test_build_executor_tool_plan_prompt_includes_tool_descriptions():
    state = create_initial_state(original_question="What is LangGraph?")
    _add_planner_output(state, PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    prompt = build_executor_tool_plan_prompt(state, "st_1")
    assert "web.search" in prompt
    assert "web.fetch_extract" in prompt
    assert "web.download_pdf" in prompt


def test_build_supervisor_prompt_requests_json_with_route():
    state = create_initial_state(original_question="What is LangGraph?")
    _add_planner_output(state, PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    prompt = build_supervisor_prompt(state)
    assert "route" in prompt
    assert "continue_execution" in prompt
    assert "revise_plan" in prompt
    assert "curate" in prompt
    assert "fail" in prompt


def test_build_curator_prompt_requests_json_with_title_and_summary():
    state = create_initial_state(original_question="What is LangGraph?")
    _add_planner_output(state, PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    prompt = build_curator_prompt(state)
    assert "title" in prompt
    assert "summary" in prompt
    assert "JSON" in prompt or "json" in prompt


# ── R-109: build_executor_context raises ResearchError for missing subtask ──


def test_build_executor_context_raises_research_error_for_missing_subtask():
    """When subtask_id is not found, raise ResearchError (not ValueError)."""
    import pytest

    state = create_initial_state(original_question="What is LangGraph?")
    with pytest.raises(ResearchError, match="not found"):
        build_executor_context(state, "st_nonexistent")
