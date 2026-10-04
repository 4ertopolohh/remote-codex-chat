"""Exercise the approval broker with real Codex in a disposable Git repository."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from pathlib import Path

from codex_bridge import CodexBridge, RequestPending, TurnCompleted


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="rc006-approval-") as directory:
        project = Path(directory)
        init = await asyncio.create_subprocess_exec("git", "init", "-q", str(project))
        if await init.wait() != 0:
            raise RuntimeError("git init failed")
        bridge = CodexBridge(approval_timeout=90)
        await bridge.start()
        evidence: list[dict[str, str]] = []
        try:
            thread_id = await bridge.start_thread(project, approval_policy="untrusted")
            turn_id = await bridge.start_turn(
                thread_id,
                "Run the shell command `echo RC006_OK` once, then report its output. Do not edit files.",
            )
            while True:
                event = await bridge.next_event(timeout=180)
                if isinstance(event, RequestPending):
                    command = event.details.get("command", "")
                    allowed = isinstance(command, str) and (
                        command.strip().lower() == "echo rc006_ok"
                        or bool(
                            re.fullmatch(
                                r'"[^"\n]*\\pwsh\.exe" -Command \'echo RC006_OK\'',
                                command,
                            )
                        )
                    )
                    decision = (
                        "accept" if event.kind == "command" and allowed else "decline"
                    )
                    await bridge.answer_request(event.id, decision)
                    evidence.append(
                        {
                            "kind": event.kind,
                            "command": str(command),
                            "decision": decision,
                        }
                    )
                if isinstance(event, TurnCompleted) and event.turn_id == turn_id:
                    status = await asyncio.create_subprocess_exec(
                        "git",
                        "status",
                        "--short",
                        cwd=project,
                        stdout=asyncio.subprocess.PIPE,
                    )
                    output, _ = await status.communicate()
                    print(
                        json.dumps(
                            {
                                "status": event.status,
                                "approvals": evidence,
                                "git_status": output.decode().strip(),
                            }
                        )
                    )
                    break
        finally:
            await bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
