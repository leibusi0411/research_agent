from research_agent.web.context import (
    build_curator_context,
    build_executor_context,
    build_planner_context,
    build_supervisor_context,
)
from research_agent.web.prompt_builders import (
    build_curator_prompt,
    build_executor_prompt,
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
    WebResearchState,
    WebSource,
)


def test_build_planner_prompt_contains_original_question():
    state = WebResearchState(original_question="What is LangGraph?")
    prompt = build_planner_prompt(state)
    assert "What is LangGraph?" in prompt
    assert "research_title" in prompt
    assert "subtasks" in prompt


def test_build_planner_prompt_for_revision_contains_existing_plan():
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Initial subtask")]))
    prompt = build_planner_prompt(state, revision=True)
    assert "Initial subtask" in prompt
    assert "revise" in prompt.lower()


def test_build_executor_prompt_contains_subtask_question():
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    prompt = build_executor_prompt(state, "st_1")
    assert "Find architecture overview." in prompt
    assert "search" in prompt.lower()
    assert "fetch" in prompt.lower()


def test_build_supervisor_prompt_contains_current_plan():
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    prompt = build_supervisor_prompt(state)
    assert "Find architecture overview." in prompt
    assert "route" in prompt.lower()


def test_build_supervisor_prompt_contains_executor_outputs():
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    source = WebSource(source_id="src_1", title="Docs", url="https://example.com", fetched_at="2026-06-23T10:00:00Z")
    finding = Finding(finding_id="f_1", subtask_id="st_1", text="LangGraph supports state graphs.", source_ids=["src_1"])
    executor_output = ExecutorOutput(subtask_id="st_1", status="completed", findings=[finding], sources=[source])
    state.merge_executor_output(executor_output)
    prompt = build_supervisor_prompt(state)
    assert "LangGraph supports state graphs." in prompt


def test_build_curator_prompt_contains_findings():
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    source = WebSource(source_id="src_1", title="Docs", url="https://example.com", fetched_at="2026-06-23T10:00:00Z")
    finding = Finding(finding_id="f_1", subtask_id="st_1", text="LangGraph supports state graphs.", source_ids=["src_1"])
    executor_output = ExecutorOutput(subtask_id="st_1", status="completed", findings=[finding], sources=[source])
    state.merge_executor_output(executor_output)
    prompt = build_curator_prompt(state)
    assert "LangGraph supports state graphs." in prompt
    assert "summary" in prompt.lower()
    assert "title" in prompt.lower()


def test_build_planner_prompt_for_initial_plan_requests_3_to_5_subtasks():
    state = WebResearchState(original_question="What is LangGraph?")
    prompt = build_planner_prompt(state)
    assert "3-5" in prompt or "3 to 5" in prompt


def test_build_planner_prompt_for_revision_requests_1_to_3_subtasks():
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Initial subtask")]))
    prompt = build_planner_prompt(state, revision=True)
    assert "1-3" in prompt or "1 to 3" in prompt


def test_build_executor_prompt_includes_tool_descriptions():
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    prompt = build_executor_prompt(state, "st_1")
    assert "web.search" in prompt
    assert "web.fetch_extract" in prompt
    assert "web.download_pdf" in prompt


def test_build_supervisor_prompt_requests_json_with_route():
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    prompt = build_supervisor_prompt(state)
    assert "route" in prompt
    assert "continue_execution" in prompt
    assert "revise_plan" in prompt
    assert "curate" in prompt
    assert "fail" in prompt


def test_build_curator_prompt_requests_json_with_title_and_summary():
    state = WebResearchState(original_question="What is LangGraph?")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Find architecture overview.")]))
    prompt = build_curator_prompt(state)
    assert "title" in prompt
    assert "summary" in prompt
    assert "JSON" in prompt or "json" in prompt