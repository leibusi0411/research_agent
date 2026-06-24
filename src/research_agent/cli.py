from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from research_agent.core.config import InitConfigRequest, default_config_path, load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.service import CoreService
from research_agent.web.fake_runtime import FakeWebResearchRuntime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="research-agent")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Initialize user configuration.")
    init_parser.add_argument("--default-workspace", required=True)
    init_parser.add_argument("--knowledge-base-path", required=True)
    init_parser.add_argument("--chat-base-url", required=True)
    init_parser.add_argument("--chat-api-key", required=True)
    init_parser.add_argument("--chat-model", required=True)
    init_parser.add_argument("--embedding-base-url", required=True)
    init_parser.add_argument("--embedding-api-key", required=True)
    init_parser.add_argument("--embedding-model", required=True)
    init_parser.add_argument("--search-api-key", required=True)
    local_parser = subparsers.add_parser("local", help="Run Local RAG research.")
    local_parser.add_argument("question", nargs="?")
    web_parser = subparsers.add_parser("web", help="Run Web Research.")
    web_parser.add_argument("question", nargs="?")
    both_parser = subparsers.add_parser("both", help="Run Local RAG and Web Research as separate tasks.")
    both_parser.add_argument("question", nargs="?")

    task_parser = subparsers.add_parser("task", help="Manage task history.")
    task_subparsers = task_parser.add_subparsers(dest="task_command")
    task_subparsers.add_parser("list", help="List finished tasks.")

    kb_parser = subparsers.add_parser("kb", help="Maintain the Knowledge Base Index.")
    kb_subparsers = kb_parser.add_subparsers(dest="kb_command")
    kb_subparsers.add_parser("status", help="Show Knowledge Base Index status.")
    kb_subparsers.add_parser("rebuild", help="Rebuild the Knowledge Base Index.")

    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "init":
        return _run_init(args)
    try:
        config = load_user_config(default_config_path())
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    service = CoreService(default_workspace=config.workspace.default_workspace, config_path=default_config_path())
    if args.command == "local":
        return _run_local(args, service)
    if args.command == "web":
        return _run_web(args, service)
    if args.command == "both":
        return _run_both(args, service)
    if args.command == "task":
        return _run_task(args, service)
    if args.command == "kb":
        return _run_kb(args, service)
    print("[runtime_error] Command skeleton is not implemented in this slice.")
    return 1


def _run_init(args: argparse.Namespace) -> int:
    request = InitConfigRequest(
        default_workspace=Path(args.default_workspace),
        knowledge_base_path=Path(args.knowledge_base_path),
        chat_base_url=args.chat_base_url,
        chat_api_key=args.chat_api_key,
        chat_model=args.chat_model,
        embedding_base_url=args.embedding_base_url,
        embedding_api_key=args.embedding_api_key,
        embedding_model=args.embedding_model,
        search_api_key=args.search_api_key,
    )
    service = CoreService(default_workspace=request.default_workspace, config_path=default_config_path())
    try:
        written_path = service.init_config(request)
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    print(f"Config written: {written_path}")
    return 0


def _run_kb(args: argparse.Namespace, service: CoreService) -> int:
    if args.kb_command == "status":
        status = service.get_kb_status()
    elif args.kb_command == "rebuild":
        status = service.rebuild_kb_index()
    else:
        print("[runtime_error] Missing kb subcommand.")
        return 1
    for key in ["status", "vault_path", "file_count", "chunk_count", "last_indexed_at"]:
        print(f"{key}: {status.get(key)}")
    if "error" in status:
        print(f"error: {status['error']}")
        return 1
    return 0


def _run_local(args: argparse.Namespace, service: CoreService) -> int:
    if not args.question:
        print("[config_invalid] Local research question is required.")
        return 1
    try:
        result = service.run_local_research(args.question)
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    return _print_local_result(result)


def _print_local_result(result: dict) -> int:
    if result["status"] == "failed":
        error = result["error"]
        print(f"[{error['code']}] {error['message']}")
        return 1
    print("Local Results")
    for index, item in enumerate(result["local_results"], start=1):
        print(f"{index}. {item['text']}")
        print(f"source_path: {item['source_path']}")
        if item.get("heading_path"):
            print(f"heading_path: {' > '.join(item['heading_path'])}")
    return 0


def _run_web(args: argparse.Namespace, service: CoreService) -> int:
    if not args.question:
        print("[config_invalid] Web research question is required.")
        return 1
    runtime = FakeWebResearchRuntime(
        workspace=service.workspace.root,
        max_retrieval_rounds=int(os.environ.get("RESEARCH_AGENT_FAKE_WEB_MAX_ROUNDS", "3")),
        produce_findings=os.environ.get("RESEARCH_AGENT_FAKE_WEB_PRODUCE_FINDINGS", "1") != "0",
        fail_report_write=os.environ.get("RESEARCH_AGENT_FAKE_WEB_REPORT_FAILURE") == "1",
        schema_failure=os.environ.get("RESEARCH_AGENT_FAKE_WEB_SCHEMA_FAILURE") == "1",
        on_event=_print_web_event,
        event_delay_seconds=float(os.environ.get("RESEARCH_AGENT_FAKE_WEB_EVENT_DELAY_SECONDS", "0")),
    )
    try:
        result = service.run_web_research(args.question, runtime=runtime)
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    return _print_web_result(result)


def _print_web_result(result: dict, *, heading_prefix: str = "") -> int:
    if result["status"] == "failed":
        error = result["error"]
        print(f"[{error['code']}] {error['message']}")
        return 1
    output = result["curator_output"]
    print(f"{heading_prefix}Summary")
    print(output["summary"])
    print(f"{heading_prefix}Findings")
    for finding in output["findings"]:
        print(f"- {finding['text']}")
    print(f"{heading_prefix}Sources")
    for source in output["sources"]:
        print(f"- {source['title']} - {source['url']}")
    print(f"{heading_prefix}report_path: {result['report_path']}")
    return 0


def _run_both(args: argparse.Namespace, service: CoreService) -> int:
    if not args.question:
        print("[config_invalid] Research question is required.")
        return 1
    runtime = FakeWebResearchRuntime(
        workspace=service.workspace.root,
        max_retrieval_rounds=int(os.environ.get("RESEARCH_AGENT_FAKE_WEB_MAX_ROUNDS", "3")),
        produce_findings=os.environ.get("RESEARCH_AGENT_FAKE_WEB_PRODUCE_FINDINGS", "1") != "0",
        fail_report_write=os.environ.get("RESEARCH_AGENT_FAKE_WEB_REPORT_FAILURE") == "1",
        schema_failure=os.environ.get("RESEARCH_AGENT_FAKE_WEB_SCHEMA_FAILURE") == "1",
        on_event=lambda event: _print_web_event({**event, "phase": f"web:{event['phase']}"}),
        event_delay_seconds=float(os.environ.get("RESEARCH_AGENT_FAKE_WEB_EVENT_DELAY_SECONDS", "0")),
    )
    result = service.run_both(args.question, web_runtime=runtime)
    print("Local")
    local = result["local"]
    if local["status"] == "failed":
        error = local["error"]
        print(f"[local:{error['code']}] {error['message']}")
        local_code = 1
    else:
        local_code = _print_local_result(local)
    print("Web")
    web = result["web"]
    if web["status"] == "failed":
        error = web["error"]
        print(f"[web:{error['code']}] {error['message']}")
        web_code = 1
    else:
        web_code = _print_web_result(web, heading_prefix="Web ")
    return 0 if local_code == 0 and web_code == 0 else 1


def _run_task(args: argparse.Namespace, service: CoreService) -> int:
    if args.task_command != "list":
        print("[runtime_error] Unsupported task subcommand in v1.")
        return 1
    records = service.list_finished_tasks()
    print("task_id mode status title_or_question created_at")
    for record in records:
        print(f"{record.task_id} {record.mode} {record.status} {record.title_or_question} {record.created_at}")
    return 0


def _print_web_event(event: dict) -> None:
    print(f"{event['phase']}: {event['message']}", flush=True)


def _print_web_events(events_path: Path) -> None:
    if not events_path.exists():
        return
    import json

    for line in events_path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        print(f"{event['phase']}: {event['message']}")


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
