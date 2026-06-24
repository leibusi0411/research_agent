import json
import sqlite3
from pathlib import Path

from research_agent.core.config import InitConfigRequest
from research_agent.core.service import CoreService
from research_agent.web.context import (
    build_curator_context,
    build_executor_context,
    build_planner_context,
    build_supervisor_context,
)
from research_agent.web.fake_runtime import FakeWebResearchRuntime
from research_agent.web.schemas import (
    ExecutorOutput,
    Finding,
    PlannerOutput,
    PlannerSubtaskDraft,
    ProgressEvent,
    SupervisorOutput,
    WebResearchState,
    WebSource,
)


def configured_service(tmp_path: Path) -> tuple[CoreService, Path, Path]:
    config_path = tmp_path / "config.toml"
    workspace = tmp_path / "runtime"
    vault = tmp_path / "vault"
    vault.mkdir()
    service = CoreService(default_workspace=workspace, config_path=config_path)
    service.init_config(
        InitConfigRequest(
            default_workspace=workspace,
            knowledge_base_path=vault,
            chat_base_url="https://models.example/v1",
            chat_api_key="chat-key",
            chat_model="chat-model",
            embedding_base_url="https://embeddings.example/v1",
            embedding_api_key="embedding-key",
            embedding_model="embedding-model",
            search_api_key="search-key",
        )
    )
    return service, config_path, workspace


def test_web_research_schema_objects_are_structured():
    planner_output = PlannerOutput(
        research_title="LangGraph Research",
        subtasks=[PlannerSubtaskDraft(question="What is LangGraph?")],
    )
    source = WebSource(source_id="src_1", title="Docs", url="https://example.com", fetched_at="2026-06-23T10:00:00Z")
    finding = Finding(finding_id="f_1", subtask_id="st_1", text="LangGraph supports state graphs.", source_ids=["src_1"])
    executor_output = ExecutorOutput(subtask_id="st_1", status="completed", findings=[finding], sources=[source])
    supervisor_output = SupervisorOutput(
        route="curate",
        reason="Enough evidence.",
        next_subtask_ids=[],
        skip_subtask_ids=[],
        plan_revision_request=None,
        research_gaps=[],
        saturation=True,
    )

    assert planner_output.subtasks[0].question == "What is LangGraph?"
    assert executor_output.findings[0].source_ids == ["src_1"]
    assert supervisor_output.route == "curate"
    progress = ProgressEvent(
        task_id="task_20260623_103000_a1b2c3",
        mode="web",
        phase="web_planning",
        event_type="started",
        created_at="2026-06-23T10:00:00Z",
        message="Planning",
        details={"items": []},
    )
    assert progress.to_dict()["phase"] == "web_planning"


def test_context_builders_return_role_specific_slices():
    state = WebResearchState(original_question="Research LangGraph")
    state.add_planner_output(PlannerOutput("LangGraph Research", [PlannerSubtaskDraft("Initial subtask")]))

    planner_context = build_planner_context(state)
    executor_context = build_executor_context(state, "st_1")
    supervisor_context = build_supervisor_context(state)
    curator_context = build_curator_context(state)

    assert planner_context.original_question == "Research LangGraph"
    assert executor_context.subtask.subtask_id == "st_1"
    assert supervisor_context.current_plan[0].status == "pending"
    assert curator_context.findings == []


def test_fake_web_runtime_executes_revision_and_curation_with_progress(tmp_path):
    _service, _config_path, workspace = configured_service(tmp_path)
    runtime = FakeWebResearchRuntime(workspace=workspace, max_retrieval_rounds=1)

    result = runtime.run("Research LangGraph architecture")

    assert result["status"] == "completed"
    assert result["curator_output"]["title"] == "Research LangGraph architecture"
    assert result["curator_output"]["summary"]
    assert result["curator_output"]["findings"]
    assert result["curator_output"]["sources"]
    assert result["report_path"].endswith(".md")
    assert Path(result["report_path"]).is_file()
    assert result["state"].subtasks[0].subtask_id == "st_1"
    assert any(subtask.status == "skipped" for subtask in result["state"].subtasks)
    assert any(subtask.subtask_id == "st_3" for subtask in result["state"].subtasks)
    assert result["state"].research_gaps == ["Need implementation examples."]

    event_lines = (workspace / "tasks" / result["task_id"] / "events.jsonl").read_text(encoding="utf-8").splitlines()
    phases = [json.loads(line)["phase"] for line in event_lines]
    assert "web_planning" in phases
    assert "web_execution" in phases
    assert "web_supervision" in phases
    assert "web_revision" in phases
    assert "web_curation" in phases

    persisted = json.loads((workspace / "tasks" / result["task_id"] / "result.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "completed"
    assert persisted["report_path"] == result["report_path"]
    assert persisted["curator_output"]["findings"][0]["source_ids"]
    with sqlite3.connect(workspace / "tasks.sqlite") as connection:
        row = connection.execute("SELECT mode, status, report_path FROM tasks WHERE task_id = ?", (result["task_id"],)).fetchone()
    assert row == ("web", "completed", result["report_path"])


def test_fake_runtime_continue_execution_uses_next_subtask_ids(tmp_path):
    _service, _config_path, workspace = configured_service(tmp_path)
    runtime = FakeWebResearchRuntime(
        workspace=workspace,
        max_retrieval_rounds=3,
        first_supervisor_route="continue_execution",
    )

    result = runtime.run("Research continue route")

    assert result["status"] == "completed"
    assert result["state"].last_supervisor_output.route == "curate"
    assert "continue_execution" in result["state"].route_history
    assert any(output.subtask_id == "st_2" for output in result["state"].executor_outputs)


def test_runtime_route_guard_curates_at_retrieval_limit_when_findings_exist(tmp_path):
    _service, _config_path, workspace = configured_service(tmp_path)
    runtime = FakeWebResearchRuntime(workspace=workspace, max_retrieval_rounds=0)

    result = runtime.run("Research route guard")

    assert result["status"] == "completed"
    assert result["state"].last_supervisor_output.route == "continue_execution"
    assert result["state"].route_history[-1] == "curate"


def test_runtime_route_guard_fails_at_limit_without_findings(tmp_path):
    _service, _config_path, workspace = configured_service(tmp_path)
    runtime = FakeWebResearchRuntime(workspace=workspace, max_retrieval_rounds=0, produce_findings=False)

    result = runtime.run("Research empty route guard")

    assert result["status"] == "failed"
    assert result["error"]["code"] == "runtime_error"
    assert result["state"].route_history[-1] == "fail"


def test_fake_runtime_marks_task_failed_when_report_write_fails(tmp_path):
    _service, _config_path, workspace = configured_service(tmp_path)
    runtime = FakeWebResearchRuntime(workspace=workspace, max_retrieval_rounds=1, fail_report_write=True)

    result = runtime.run("Research report failure")

    assert result["status"] == "failed"
    assert result["error"]["code"] == "file_write_error"
    assert "report_path" not in result
    persisted = json.loads((workspace / "tasks" / result["task_id"] / "result.json").read_text(encoding="utf-8"))
    assert persisted["status"] == "failed"
    assert persisted["error"]["code"] == "file_write_error"
    with sqlite3.connect(workspace / "tasks.sqlite") as connection:
        row = connection.execute("SELECT mode, status, report_path FROM tasks WHERE task_id = ?", (result["task_id"],)).fetchone()
    assert row == ("web", "failed", None)
