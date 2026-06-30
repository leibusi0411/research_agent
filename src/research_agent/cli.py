from __future__ import annotations

import argparse
import sys
from pathlib import Path

from research_agent.core.config import InitConfigRequest, default_config_path, load_user_config
from research_agent.core.errors import ResearchError
from research_agent.core.service import CoreService


def _format_error_message(exc: Exception) -> str:
    if isinstance(exc, ResearchError):
        return f"[{exc.code}] {exc.message}"
    return f"[runtime_error] Unexpected error: {exc}"


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
    try:
        return _main(argv)
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI top-level catch-all
        print(_format_error_message(exc))
        return 1


def _main(argv: list[str] | None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "init":
        return _run_init(args)
    try:
        config = load_user_config(default_config_path())
        service = CoreService(default_workspace=config.workspace.default_workspace, config_path=default_config_path())
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI fallback
        print(_format_error_message(exc))
        return 1
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
    except Exception as exc:  # noqa: BLE001 - CLI fallback
        print(_format_error_message(exc))
        return 1
    print(f"Config written: {written_path}")
    return 0


def _run_kb(args: argparse.Namespace, service: CoreService) -> int:
    try:
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
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI fallback
        print(_format_error_message(exc))
        return 1


def _run_local(args: argparse.Namespace, service: CoreService) -> int:
    if not args.question:
        print("[config_invalid] Local research question is required.")
        return 1
    try:
        result = service.run_local_research(args.question)
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI fallback
        print(_format_error_message(exc))
        return 1
    return _print_local_result(result)


def _print_local_result(result: dict) -> int:
    if result.get("status") == "failed":
        error = result.get("error", {})
        print(f"[{error.get('code', 'unknown')}] {error.get('message', 'Unknown error')}")
        return 1
    print("Local Results")
    for index, item in enumerate(result.get("local_results", []), start=1):
        print(f"{index}. {item.get('text', '')}")
        print(f"source_path: {item.get('source_path', '')}")
        heading = item.get("heading_path")
        if heading:
            print(f"heading_path: {' > '.join(heading)}")
    return 0


def _run_web(args: argparse.Namespace, service: CoreService) -> int:
    if not args.question:
        print("[config_invalid] Web research question is required.")
        return 1
    try:
        # on_event callback IS the CLI's EventStream consumer.
        # It is threaded through create_provider_runtime -> ProviderBackedWebResearchRuntime
        # -> StateGraphRunner._emit -> self.on_event (see R-33 fix).
        # Events carry _seq and event_subtype for rich formatting.
        result = service.run_web_research(args.question, on_event=_print_web_event)
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI fallback
        print(_format_error_message(exc))
        return 1
    return _print_web_result(result)


def _print_web_result(result: dict, *, heading_prefix: str = "") -> int:
    if result.get("status") == "failed":
        error = result.get("error", {})
        print(f"[{error.get('code', 'unknown')}] {error.get('message', 'Unknown error')}")
        return 1
    output = result.get("curator_output", {})
    print(f"{heading_prefix}Summary")
    print(output.get("summary", ""))
    print(f"{heading_prefix}Findings")
    for finding in output.get("findings", []):
        print(f"- {finding.get('text', '')}")
    print(f"{heading_prefix}Sources")
    for source in output.get("sources", []):
        print(f"- {source.get('title', '')} - {source.get('url', '')}")
    report_path = result.get("report_path", "")
    if report_path:
        print(f"{heading_prefix}report_path: {report_path}")
    return 0


def _run_both(args: argparse.Namespace, service: CoreService) -> int:
    if not args.question:
        print("[config_invalid] Research question is required.")
        return 1
    try:
        result = service.run_both(args.question, on_event=_print_both_web_event)
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI fallback
        print(_format_error_message(exc))
        return 1
    print("Local")
    local = result.get("local", {})
    if local.get("status") == "failed":
        error = local.get("error", {})
        print(f"[local:{error.get('code', 'unknown')}] {error.get('message', 'Unknown error')}")
        local_code = 1
    else:
        local_code = _print_local_result(local)
    print("Web")
    web = result.get("web", {})
    if web.get("status") == "failed":
        error = web.get("error", {})
        print(f"[web:{error.get('code', 'unknown')}] {error.get('message', 'Unknown error')}")
        web_code = 1
    else:
        web_code = _print_web_result(web, heading_prefix="Web ")
    return 0 if local_code == 0 and web_code == 0 else 1


def _run_task(args: argparse.Namespace, service: CoreService) -> int:
    try:
        if args.task_command != "list":
            print("[runtime_error] Unsupported task subcommand in v1.")
            return 1
        records = service.list_finished_tasks()
        print("task_id mode status title_or_question created_at")
        for record in records:
            print(f"{record.task_id} {record.mode} {record.status} {record.title_or_question} {record.created_at}")
        return 0
    except ResearchError as error:
        print(f"[{error.code}] {error.message}")
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI fallback
        print(_format_error_message(exc))
        return 1


def _first_item(event: dict) -> dict:
    """Safely extract the first details item as a dict.

    Returns an empty dict when items is empty or its first element is not a dict
    (defensive against malformed event data; R-82).
    """
    items = event.get("details", {}).get("items", [])
    item0 = items[0] if items else None
    return item0 if isinstance(item0, dict) else {}


def _print_web_event(event: dict) -> None:
    phase = event.get("phase", "")
    subtype = event.get("event_subtype")
    msg = event.get("message", "")
    if subtype == "tool_call":
        item = _first_item(event)
        tool_name = item.get("name", "?")
        tool_input = item.get("input", "")[:80]
        print(f"[{phase}] {tool_name}: {tool_input}", flush=True)
    elif subtype == "finding":
        item = _first_item(event)
        text = item.get("text", "")[:120] or msg
        print(f"[{phase}] finding: {text}", flush=True)
    elif subtype == "source":
        item = _first_item(event)
        title = item.get("title", "")
        url = item.get("url", "")[:80]
        print(f"[{phase}] source: {title} ({url})", flush=True)
    elif subtype == "subtask_completed":
        item = _first_item(event)
        if item:
            n_findings = item.get("finding_count", 0)
            n_sources = item.get("source_count", 0)
            print(f"[{phase}] subtask_done: {n_findings} findings, {n_sources} sources", flush=True)
        else:
            print(f"[{phase}] {msg}", flush=True)
    elif subtype == "subtask_failed":
        item = _first_item(event)
        error = item.get("error", "?")[:100]
        print(f"[{phase}] subtask_failed: {error}", flush=True)
    else:
        print(f"[{phase}] {msg}", flush=True)


def _print_both_web_event(event: dict) -> None:
    _print_web_event({**event, "phase": f"web:{event.get('phase', '')}"})


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    raise SystemExit(main())
