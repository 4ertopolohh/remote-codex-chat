from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from codex_bridge._transport import (
    AppServerClient,
    AppServerError,
    AppServerRpcError,
    IncomingEvent,
    ServerRequest,
)

APPROVAL_METHODS = {
    "item/commandExecution/requestApproval",
    "item/fileChange/requestApproval",
}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Phase 0 PoC client for codex app-server over stdio."
    )
    parser.add_argument(
        "--codex-bin", default="codex", help="Codex executable name or path."
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=60.0,
        help="Timeout for individual RPC requests in seconds.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("models", help="Run model/list and print the response.")
    subparsers.add_parser(
        "limits", help="Run account/rateLimits/read and print the response."
    )

    chat = subparsers.add_parser("chat", help="Start a thread and run one turn.")
    _add_turn_args(chat, needs_project=True)
    chat.add_argument(
        "--approval-policy",
        choices=("untrusted", "on-request", "never"),
        default=None,
        help="Optional thread approval policy override.",
    )

    resume = subparsers.add_parser(
        "resume", help="Resume a persisted thread and run one turn."
    )
    resume.add_argument("--thread-id", required=True)
    _add_turn_args(resume, needs_project=False)

    return parser


def _add_turn_args(parser: argparse.ArgumentParser, *, needs_project: bool) -> None:
    if needs_project:
        parser.add_argument(
            "--project",
            type=Path,
            required=True,
            help="Disposable local Git repository used as the Codex cwd.",
        )
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--approval-mode",
        choices=("prompt", "accept", "decline"),
        default="prompt",
        help="How the PoC responds to command/file approval requests.",
    )
    parser.add_argument(
        "--interrupt-after",
        type=float,
        default=None,
        help="Send turn/interrupt after N seconds. Omit for a normal turn.",
    )
    parser.add_argument(
        "--event-timeout",
        type=float,
        default=300.0,
        help="Maximum seconds to wait for the turn to complete.",
    )


async def _run(args: argparse.Namespace) -> int:
    command = (args.codex_bin, "app-server", "--listen", "stdio://")
    client = AppServerClient(command, request_timeout=args.request_timeout)

    try:
        async with client:
            init = await client.initialize()
            print(
                f"Initialized app-server: {init.get('userAgent', 'unknown user-agent')}"
            )

            if args.command == "models":
                result = await client.request("model/list", {})
                _print_json(result)
                return 0

            if args.command == "limits":
                result = await client.request("account/rateLimits/read", {})
                _print_json(result)
                return 0

            if args.command == "chat":
                project = args.project.expanduser().resolve()
                if not project.is_dir():
                    raise AppServerError(f"Project directory does not exist: {project}")

                thread_params: dict[str, Any] = {"cwd": str(project)}
                if args.model:
                    thread_params["model"] = args.model
                if args.approval_policy:
                    thread_params["approvalPolicy"] = args.approval_policy

                thread_result = await client.request("thread/start", thread_params)
                thread_id = _extract_thread_id(thread_result)
                print(f"THREAD_ID={thread_id}")
                return await _run_turn(client, thread_id, args)

            if args.command == "resume":
                resume_result = await client.request(
                    "thread/resume",
                    {"threadId": args.thread_id, "excludeTurns": True},
                )
                thread_id = _extract_thread_id(resume_result)
                print(f"THREAD_ID={thread_id}")
                return await _run_turn(client, thread_id, args)

            raise AppServerError(f"Unsupported command: {args.command}")
    except (AppServerError, AppServerRpcError) as exc:
        print(f"PoC failed: {exc}", file=sys.stderr)
        if client.stderr_tail:
            print("codex app-server stderr tail:", file=sys.stderr)
            for line in client.stderr_tail:
                print(f"  {line}", file=sys.stderr)
        return 1


async def _run_turn(
    client: AppServerClient,
    thread_id: str,
    args: argparse.Namespace,
) -> int:
    turn_result = await client.request(
        "turn/start",
        {
            "threadId": thread_id,
            "input": [{"type": "text", "text": args.prompt}],
        },
    )
    turn_id = _extract_turn_id(turn_result)
    print(f"TURN_ID={turn_id}")

    interrupt_task: asyncio.Task[None] | None = None
    if args.interrupt_after is not None:
        interrupt_task = asyncio.create_task(
            _interrupt_later(client, thread_id, turn_id, args.interrupt_after)
        )

    loop = asyncio.get_running_loop()
    deadline = loop.time() + args.event_timeout

    try:
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise AppServerError("Timed out waiting for turn/completed")

            event = await client.next_event(timeout=remaining)
            _print_event(event)

            if isinstance(event, ServerRequest):
                await _handle_server_request(client, event, args.approval_mode)
                continue

            if event.method == "item/agentMessage/delta":
                delta = event.params.get("delta")
                if isinstance(delta, str):
                    print(delta, end="", flush=True)

            if event.method == "turn/completed":
                turn = event.params.get("turn")
                status = turn.get("status") if isinstance(turn, dict) else None
                if status is None:
                    status = event.params.get("status")
                print()
                print(f"TURN_STATUS={status or 'unknown'}")
                return 0 if status == "completed" else 2
    finally:
        if interrupt_task is not None:
            if not interrupt_task.done():
                interrupt_task.cancel()
            await asyncio.gather(interrupt_task, return_exceptions=True)


async def _interrupt_later(
    client: AppServerClient,
    thread_id: str,
    turn_id: str,
    delay: float,
) -> None:
    await asyncio.sleep(delay)
    await client.request(
        "turn/interrupt",
        {"threadId": thread_id, "turnId": turn_id},
    )
    print(f"\nInterrupt requested after {delay:.2f}s")


async def _handle_server_request(
    client: AppServerClient,
    event: ServerRequest,
    approval_mode: str,
) -> None:
    if event.method not in APPROVAL_METHODS:
        await client.respond_error(
            event.request_id,
            code=-32601,
            message=f"PoC client does not handle server request {event.method}",
        )
        return

    decision = approval_mode
    if approval_mode == "prompt":
        summary = _approval_summary(event)
        answer = await asyncio.to_thread(
            input,
            f"\nApproval required: {summary}\nAccept? [y/N]: ",
        )
        decision = "accept" if answer.strip().lower() in {"y", "yes"} else "decline"

    await client.respond(event.request_id, {"decision": decision})
    print(f"Approval response: {decision}")


def _approval_summary(event: ServerRequest) -> str:
    params = event.params
    if event.method == "item/commandExecution/requestApproval":
        command = params.get("command")
        cwd = params.get("cwd")
        return f"command={command!r}, cwd={cwd!r}"
    changes = params.get("changes")
    return f"file changes={changes!r}"


def _extract_thread_id(result: Any) -> str:
    if not isinstance(result, dict):
        raise AppServerError("Thread RPC returned a non-object result")
    thread = result.get("thread")
    if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
        raise AppServerError("Thread RPC response does not contain thread.id")
    return thread["id"]


def _extract_turn_id(result: Any) -> str:
    if not isinstance(result, dict):
        raise AppServerError("turn/start returned a non-object result")
    turn = result.get("turn")
    if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
        raise AppServerError("turn/start response does not contain turn.id")
    return turn["id"]


def _print_event(event: IncomingEvent) -> None:
    kind = "request" if isinstance(event, ServerRequest) else "notification"
    payload = {
        "kind": kind,
        "method": event.method,
        "params": event.params,
    }
    if isinstance(event, ServerRequest):
        payload["id"] = event.request_id
    print(f"\nEVENT {json.dumps(payload, ensure_ascii=False)}")


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        print("\nInterrupted by user.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
