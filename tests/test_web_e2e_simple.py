"""Simple end-to-end tests to verify real API connections work with Web Research components."""

from pathlib import Path

import pytest

from research_agent.core.config import load_user_config
from research_agent.core.providers import OpenAICompatibleChatModel
from research_agent.web.prompt_builders import (
    build_planner_prompt,
    build_executor_tool_plan_prompt,
    build_supervisor_prompt,
    build_curator_prompt,
)
from research_agent.web.schemas import (
    PlannerOutput,
    PlannerSubtaskDraft,
    ResearchSubtask,
    create_initial_state,
)
from research_agent.web.executor import _normalize_tool_call_payload
from research_agent.web.tools import TavilySearchProvider


def _get_config_or_skip():
    """Load config, skip test if not available."""
    try:
        config = load_user_config()
        if not config.chat_model.api_key or config.chat_model.api_key == "test-key":
            pytest.skip("Chat model API key not configured")
        if not config.search.api_key or config.search.api_key == "test-key":
            pytest.skip("Search API key not configured")
        return config
    except Exception as e:
        pytest.skip(f"Config not available: {e}")


@pytest.mark.e2e
def test_planner_prompt_with_real_llm(tmp_path):
    """Test planner prompt with real LLM."""
    config = _get_config_or_skip()

    chat_model = OpenAICompatibleChatModel.from_config(config.chat_model)

    # Create a simple state
    state = create_initial_state(original_question="What is Python?")

    # Build prompt
    prompt = build_planner_prompt(state)

    # Call LLM via native function calling
    result = chat_model.complete_tool(
        prompt=prompt,
        tool_name="plan_output",
        tool_schema={
            "type": "object",
            "properties": {
                "research_title": {"type": "string"},
                "subtasks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"question": {"type": "string"}},
                    },
                },
            },
        },
    )

    data = _normalize_tool_call_payload(result.arguments)
    assert "research_title" in data, "Response should have research_title"
    assert "subtasks" in data, "Response should have subtasks"
    assert len(data["subtasks"]) > 0, "Should have at least one subtask"

    print(f"\n[PASS] Planner prompt works with real LLM!")
    print(f"   Title: {data['research_title']}")
    print(f"   Subtasks: {len(data['subtasks'])}")


@pytest.mark.e2e
def test_search_api_with_tavily(tmp_path):
    """Test Tavily search API."""
    config = _get_config_or_skip()

    search_provider = TavilySearchProvider(api_key=config.search.api_key)

    # Perform search
    results = search_provider.search("Python GIL", max_results=3)

    assert len(results) > 0, "Should have at least one search result"

    print(f"\n[PASS] Tavily search works!")
    print(f"   Results: {len(results)}")
    for i, r in enumerate(results[:2]):
        print(f"   {i+1}. {r.get('title', 'N/A')}")


@pytest.mark.e2e
def test_executor_prompt_with_real_llm(tmp_path):
    """Test executor prompt with real LLM."""
    config = _get_config_or_skip()

    chat_model = OpenAICompatibleChatModel.from_config(config.chat_model)

    # Create state with a subtask
    state = create_initial_state(original_question="What is Python?")
    state["research_title"] = "Python Research"
    state["subtasks"] = [ResearchSubtask(subtask_id="st_1", question="What is Python's GIL?")]

    # Build executor tool plan prompt
    prompt = build_executor_tool_plan_prompt(state, "st_1")

    # Call LLM via native function calling
    result = chat_model.complete_tool(
        prompt=prompt,
        tool_name="executor_tool_plan",
        tool_schema={
            "type": "object",
            "properties": {
                "tool_calls": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "arguments": {"type": "object"},
                        },
                    },
                },
            },
        },
    )

    data = _normalize_tool_call_payload(result.arguments)
    assert "tool_calls" in data, "Response should have tool_calls"
    assert isinstance(data["tool_calls"], list), "tool_calls should be a list"
    if data["tool_calls"]:
        tc = data["tool_calls"][0]
        assert "name" in tc, "Each tool call should have a name"
        assert "arguments" in tc, "Each tool call should have arguments"

    print(f"\n[PASS] Executor tool plan prompt works with real LLM!")
    print(f"   Tool calls: {len(data['tool_calls'])}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
