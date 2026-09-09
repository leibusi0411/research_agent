from __future__ import annotations

import json
from typing import Any

from research_agent.core.providers import ToolCallResult
from research_agent.web.graph import GraphContext, _plan_node
from research_agent.web.prompt_builders import (
    build_planner_prompt,
    build_planner_survey_prompt,
)
from research_agent.web.schemas import PriorKnowledgeChunk


class _ScriptedChatModel:
    """complete_tool pops scripted JSON payloads; records every call."""

    def __init__(self, payloads: list[dict[str, Any] | Exception]) -> None:
        self._payloads = list(payloads)
        self.calls: list[tuple[str, str]] = []

    def complete_tool(self, prompt: str, *, tool_name: str, tool_schema: dict[str, Any]) -> ToolCallResult:
        self.calls.append((tool_name, prompt))
        result = self._payloads.pop(0)
        if isinstance(result, Exception):
            raise result
        return ToolCallResult(name=tool_name, arguments=result)


class _FakeRetriever:
    def __init__(self, results: dict[str, list[PriorKnowledgeChunk]] | None = None) -> None:
        self.queries: list[str] = []
        self._results = results or {}

    def __call__(self, question: str) -> list[PriorKnowledgeChunk]:
        self.queries.append(question)
        return self._results.get(question, [])


def _state() -> dict[str, Any]:
    return {
        "original_question": "RAG 的全流程是什么",
        "subtasks": [],
        "executor_outputs": [],
        "research_gaps": [],
    }


def _ctx(model, retriever=None, index_updater=None) -> GraphContext:
    return GraphContext(
        chat_models={"planner": model},
        executor=None,
        max_retrieval_rounds=3,
        task_id="task_20260909_000000_survey",
        _emit=lambda *args, **kwargs: None,
        _save_llm_call_artifact=lambda *args, **kwargs: None,
        _save_source_snapshots=lambda *args, **kwargs: None,
        local_retriever=retriever,
        index_updater=index_updater,
    )


def test_survey_prompt_contains_question_and_local_kb_intent():
    prompt = build_planner_survey_prompt(_state())
    assert "RAG 的全流程是什么" in prompt
    assert "local" in prompt.lower()
    assert "3" in prompt  # query cap is communicated


def test_planner_prompt_renders_local_survey_results():
    survey = [
        {
            "query": "RAG 检索流程",
            "text": "GIL 锁住的是 eval loop。",
            "source_path": "D:/vault/gil.md",
            "heading_path": ["GIL"],
            "hits": 2,
        }
    ]
    prompt = build_planner_prompt(_state(), local_survey=survey)
    assert "local_kb_search" in prompt
    assert "GIL 锁住的是 eval loop。" in prompt
    assert "D:/vault/gil.md" in prompt
    assert "仅供参考" in prompt


def test_plan_node_surveys_local_kb_before_planning():
    retriever = _FakeRetriever(
        {"RAG 检索流程": [PriorKnowledgeChunk(text="本地 RAG 笔记内容", source_path="D:/vault/rag.md", heading_path=["RAG"])]}
    )
    model = _ScriptedChatModel(
        [
            {"queries": ["RAG 检索流程", "RAG 评估方法", "RAG 框架对比", "多余的查询"]},
            {"research_title": "RAG 全流程", "subtasks": [{"question": "子任务一"}]},
        ]
    )
    result = _plan_node(_state(), _ctx(model, retriever=retriever))

    # Survey ran first with the planner's own queries (capped at 3)…
    assert retriever.queries == ["RAG 检索流程", "RAG 评估方法", "RAG 框架对比"]
    # …and the final planning call received the survey results in its prompt.
    survey_tool, plan_prompt = model.calls[1]
    assert survey_tool == "plan_output"
    assert "本地 RAG 笔记内容" in plan_prompt
    assert "D:/vault/rag.md" in plan_prompt
    assert [s.question for s in result["subtasks"]] == ["子任务一"]


def test_plan_node_skips_survey_without_local_retriever():
    model = _ScriptedChatModel(
        [{"research_title": "T", "subtasks": [{"question": "q"}]}]
    )
    _plan_node(_state(), _ctx(model, retriever=None))
    assert [tool for tool, _prompt in model.calls] == ["plan_output"]


def test_plan_node_survives_survey_llm_failure():
    retriever = _FakeRetriever()
    model = _ScriptedChatModel(
        [
            ValueError("LLM returned invalid JSON: attempt 1"),
            ValueError("LLM returned invalid JSON: attempt 2"),
            {"research_title": "T", "subtasks": [{"question": "q"}]},
        ]
    )
    result = _plan_node(_state(), _ctx(model, retriever=retriever))
    # The survey is auxiliary: its failure (after the built-in retry) must not
    # kill the planning phase.
    assert [tool for tool, _prompt in model.calls] == [
        "local_kb_search",
        "local_kb_search",
        "plan_output",
    ]
    assert [s.question for s in result["subtasks"]] == ["q"]


def test_plan_node_runs_index_auto_update_when_wired():
    updates: list[bool] = []

    def index_updater() -> dict[str, Any]:
        updates.append(True)
        return {"status": "ready", "updated_files": 2}

    retriever = _FakeRetriever()
    model = _ScriptedChatModel(
        [{"queries": ["q1"]}, {"research_title": "T", "subtasks": [{"question": "q"}]}]
    )
    _plan_node(_state(), _ctx(model, retriever=retriever, index_updater=index_updater))
    assert updates == [True]


def test_plan_node_tolerates_index_updater_failure():
    def broken_updater() -> dict[str, Any]:
        raise OSError("index locked")

    retriever = _FakeRetriever()
    model = _ScriptedChatModel(
        [{"queries": ["q1"]}, {"research_title": "T", "subtasks": [{"question": "q"}]}]
    )
    result = _plan_node(_state(), _ctx(model, retriever=retriever, index_updater=broken_updater))
    assert [s.question for s in result["subtasks"]] == ["q"]
    assert retriever.queries == ["q1"]


def test_plan_node_skips_retrieval_when_survey_returns_empty_queries():
    retriever = _FakeRetriever()
    model = _ScriptedChatModel(
        [
            {"queries": []},
            {"research_title": "T", "subtasks": [{"question": "q"}]},
        ]
    )
    _plan_node(_state(), _ctx(model, retriever=retriever))
    assert retriever.queries == []
