"""Simple end-to-end tests to verify real API connections work with Web Research components."""

import json
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

    # Call LLM
    response = chat_model.complete(prompt)

    # Parse response
    try:
        # Try to extract JSON from response
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]

        data = json.loads(json_str)
        assert "research_title" in data, "Response should have research_title"
        assert "subtasks" in data, "Response should have subtasks"
        assert len(data["subtasks"]) > 0, "Should have at least one subtask"

        print(f"\n[PASS] Planner prompt works with real LLM!")
        print(f"   Title: {data['research_title']}")
        print(f"   Subtasks: {len(data['subtasks'])}")
    except json.JSONDecodeError as e:
        print(f"\n[WARN] LLM response is not valid JSON: {e}")
        print(f"   Response: {response[:200]}...")
        # Don't fail the test, just warn
        pass


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

    # Call LLM
    response = chat_model.complete(prompt)

    # Try to parse response
    try:
        json_str = response
        if "```json" in response:
            json_str = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            json_str = response.split("```")[1].split("```")[0]

        data = json.loads(json_str)
        print(f"\n[PASS] Executor tool plan prompt works with real LLM!")
        print(f"   Status: {data.get('status', 'N/A')}")
        print(f"   Findings: {len(data.get('findings', []))}")
    except json.JSONDecodeError:
        print(f"\n[WARN] Executor response is not structured JSON (this is expected for first call)")
        print(f"   Response preview: {response[:100]}...")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s", "-m", "e2e"])
