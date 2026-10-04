from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from codex_bridge import (
    AgentMessageDelta,
    ApprovalDeclined,
    CodexBridge,
    CodexUnavailable,
    InitializationFailed,
    MalformedProtocol,
    OperationFailed,
    ServerTerminated,
    TurnCompleted,
)


async def bridge_for(tmp_path: Path, script: str) -> CodexBridge:
    server = tmp_path / "fake_server.py"
    server.write_text(script, encoding="utf-8")
    bridge = CodexBridge(command=(sys.executable, "-S", str(server)), request_timeout=2)
    await bridge.start()
    return bridge


HANDSHAKE = """
import json, sys
def read(): return json.loads(sys.stdin.readline())
def send(x):
    print(json.dumps(x), flush=True)
init = read()
assert init['method'] == 'initialize'
send({'id': init['id'], 'result': {'userAgent': 'fake/1'}})
assert read() == {'method': 'initialized'}
"""


@pytest.mark.asyncio
async def test_thread_turn_events_and_approval_are_domain_level(tmp_path: Path) -> None:
    script = (
        HANDSHAKE
        + """
thread = read()
assert thread['method'] == 'thread/start'
assert thread['params']['cwd'] == sys.argv[1]
send({'id': thread['id'], 'result': {'thread': {'id': 'thread-1'}}})
turn = read()
assert turn['method'] == 'turn/start'
assert turn['params']['input'] == [{'type': 'text', 'text': 'hello'}]
send({'id': turn['id'], 'result': {'turn': {'id': 'turn-1'}}})
send({'method': 'item/commandExecution/requestApproval', 'id': 'rpc-5',
      'params': {'threadId': 'thread-1', 'command': 'echo hi'}})
assert read() == {'id': 'rpc-5', 'result': {'decision': 'decline'}}
send({'method': 'item/agentMessage/delta',
      'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'delta': 'hi'}})
send({'method': 'turn/completed',
      'params': {'threadId': 'thread-1', 'turn': {'id': 'turn-1', 'status': 'completed'}}})
sys.stdin.readline()
"""
    )
    script = script.replace("sys.argv[1]", repr(str(tmp_path.resolve())))
    bridge = await bridge_for(tmp_path, script)
    try:
        assert await bridge.start_thread(tmp_path) == "thread-1"
        assert await bridge.start_turn("thread-1", "hello") == "turn-1"
        assert await bridge.next_event(timeout=2) == ApprovalDeclined(
            "thread-1", "command"
        )
        assert await bridge.next_event(timeout=2) == AgentMessageDelta(
            "thread-1", "turn-1", "hi"
        )
        assert await bridge.next_event(timeout=2) == TurnCompleted(
            "thread-1", "turn-1", "completed"
        )
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_missing_executable_is_stable_error() -> None:
    bridge = CodexBridge(command=("codex-does-not-exist-rc002",), request_timeout=1)
    with pytest.raises(CodexUnavailable):
        await bridge.start()


@pytest.mark.asyncio
async def test_server_exit_wakes_event_consumer(tmp_path: Path) -> None:
    bridge = await bridge_for(tmp_path, HANDSHAKE + "sys.exit(7)\n")
    try:
        with pytest.raises(ServerTerminated, match="code 7"):
            await bridge.next_event(timeout=2)
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_malformed_notification_is_stable_error(tmp_path: Path) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + "send({'method': 'turn/completed', 'params': {}})\nsys.stdin.readline()\n",
    )
    try:
        with pytest.raises(MalformedProtocol):
            await bridge.next_event(timeout=2)
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_resume_interrupt_and_rpc_failure(tmp_path: Path) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
resume = read()
assert resume['method'] == 'thread/resume'
assert resume['params'] == {'threadId': 'thread-1', 'excludeTurns': True}
send({'id': resume['id'], 'result': {'thread': {'id': 'thread-1'}}})
interrupt = read()
assert interrupt['method'] == 'turn/interrupt'
assert interrupt['params'] == {'threadId': 'thread-1', 'turnId': 'turn-1'}
send({'id': interrupt['id'], 'result': {}})
turn = read()
send({'id': turn['id'], 'error': {'code': -32000, 'message': 'turn rejected'}})
sys.stdin.readline()
""",
    )
    try:
        assert await bridge.resume_thread("thread-1") == "thread-1"
        await bridge.interrupt_turn("thread-1", "turn-1")
        with pytest.raises(OperationFailed, match="turn rejected"):
            await bridge.start_turn("thread-1", "hello")
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_invalid_json_after_handshake_fails_event_stream(tmp_path: Path) -> None:
    marker = tmp_path / "child_closed.txt"
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + "print('{bad json', flush=True)\nsys.stdin.readline()\n"
        + f"open({str(marker)!r}, 'w').write('closed')\n",
    )
    try:
        with pytest.raises(MalformedProtocol):
            await bridge.next_event(timeout=2)
        assert not bridge.ready
        for _ in range(40):
            if marker.exists():
                break
            await asyncio.sleep(0.05)
        assert marker.read_text() == "closed"
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_failed_handshake_is_stable_error(tmp_path: Path) -> None:
    server = tmp_path / "broken_server.py"
    server.write_text("raise SystemExit(9)\n", encoding="utf-8")
    bridge = CodexBridge(command=(sys.executable, "-S", str(server)), request_timeout=2)
    with pytest.raises(InitializationFailed):
        await bridge.start()


@pytest.mark.asyncio
async def test_unlaunchable_executable_is_unavailable(tmp_path: Path) -> None:
    executable = tmp_path / "not_an_executable.txt"
    executable.write_text("hello", encoding="utf-8")
    bridge = CodexBridge(command=(str(executable),), request_timeout=1)
    with pytest.raises(CodexUnavailable):
        await bridge.start()
