from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from codex_bridge import (
    AgentMessageDelta,
    CodexBridge,
    CodexUnavailable,
    InitializationFailed,
    MalformedProtocol,
    OperationFailed,
    RequestFinished,
    RequestPending,
    ServerTerminated,
    TurnCompleted,
)


async def bridge_for(
    tmp_path: Path,
    script: str,
    *,
    experimental_features: bool = False,
    approval_timeout: float = 120.0,
) -> CodexBridge:
    server = tmp_path / "fake_server.py"
    server.write_text(script, encoding="utf-8")
    bridge = CodexBridge(
        command=(sys.executable, "-S", str(server)),
        request_timeout=2,
        experimental_features=experimental_features,
        approval_timeout=approval_timeout,
    )
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
      'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'command': 'echo hi'}})
assert read() == {'id': 'rpc-5', 'result': {'decision': 'accept'}}
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
        pending = await bridge.next_event(timeout=2)
        assert isinstance(pending, RequestPending)
        assert pending.kind == "command"
        assert pending.details == {"command": "echo hi"}
        assert not await bridge.answer_request(pending.id, "acceptForSession")
        assert await bridge.answer_request(pending.id, "accept")
        assert await bridge.next_event(timeout=2) == RequestFinished(
            pending.id, "completed"
        )
        assert not await bridge.answer_request(pending.id, "decline")
        assert await bridge.next_event(timeout=2) == AgentMessageDelta(
            "thread-1", "turn-1", "hi"
        )
        assert await bridge.next_event(timeout=2) == TurnCompleted(
            "thread-1", "turn-1", "completed"
        )
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_approval_expires_with_decline_and_cannot_be_reused(
    tmp_path: Path,
) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
send({'method': 'item/fileChange/requestApproval', 'id': 17,
      'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'reason': 'write proof'}})
assert read() == {'id': 17, 'result': {'decision': 'decline'}}
sys.stdin.readline()
""",
        approval_timeout=0.01,
    )
    try:
        pending = await bridge.next_event(timeout=2)
        assert isinstance(pending, RequestPending)
        assert pending.kind == "file_change"
        assert pending.details == {"reason": "write proof"}
        assert await bridge.next_event(timeout=2) == RequestFinished(
            pending.id, "expired"
        )
        assert not await bridge.answer_request(pending.id, "accept")
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_process_exit_cancels_pending_request(tmp_path: Path) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
send({'method': 'item/commandExecution/requestApproval', 'id': 'approval-1',
      'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'command': 'echo hi'}})
sys.exit(7)
""",
    )
    try:
        pending = await bridge.next_event(timeout=2)
        assert isinstance(pending, RequestPending)
        assert await bridge.next_event(timeout=2) == RequestFinished(
            pending.id, "cancelled"
        )
        with pytest.raises(ServerTerminated):
            await bridge.next_event(timeout=2)
        assert not await bridge.answer_request(pending.id, "accept")
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_experimental_user_input_uses_confirmed_answer_shape(
    tmp_path: Path,
) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
send({'method': 'item/tool/requestUserInput', 'id': 'question-1',
      'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'questions': [
          {'id': 'choice', 'header': 'Choice', 'question': 'Continue?',
           'options': [{'label': 'Yes', 'description': 'Proceed'}],
           'isOther': False, 'isSecret': False}]}})
assert read() == {'id': 'question-1', 'result': {'answers': {'choice': {'answers': ['Yes']}}}}
sys.stdin.readline()
""",
        experimental_features=True,
    )
    try:
        pending = await bridge.next_event(timeout=2)
        assert isinstance(pending, RequestPending)
        assert pending.kind == "user_input"
        assert not await bridge.answer_user_input(pending.id, {"wrong": ["Yes"]})
        assert await bridge.answer_user_input(pending.id, {"choice": ["Yes"]})
        assert await bridge.next_event(timeout=2) == RequestFinished(
            pending.id, "completed"
        )
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_stable_mode_rejects_experimental_user_input(tmp_path: Path) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
send({'method': 'item/tool/requestUserInput', 'id': 'question-1',
      'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'questions': []}})
assert read() == {'id': 'question-1', 'error': {'code': -32601, 'message': 'Unsupported client request'}}
sys.stdin.readline()
""",
    )
    try:
        assert not bridge.user_input_supported
        with pytest.raises(OperationFailed):
            await bridge.next_event(timeout=0.1)
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_user_input_expiry_sends_error_without_fabricating_answer(
    tmp_path: Path,
) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
send({'method': 'item/tool/requestUserInput', 'id': 'question-expire',
      'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'questions': [
          {'id': 'choice', 'header': 'Choice', 'question': 'Continue?',
           'options': None, 'isOther': True, 'isSecret': False}]}})
assert read() == {'id': 'question-expire', 'error': {'code': -32603, 'message': 'User input unavailable'}}
sys.stdin.readline()
""",
        experimental_features=True,
        approval_timeout=0.01,
    )
    try:
        pending = await bridge.next_event(timeout=2)
        assert isinstance(pending, RequestPending)
        assert await bridge.next_event(timeout=2) == RequestFinished(
            pending.id, "expired"
        )
        assert not await bridge.answer_user_input(pending.id, {"choice": ["Yes"]})
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_disconnect_cancellation_declines_original_request(
    tmp_path: Path,
) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
send({'method': 'item/commandExecution/requestApproval', 'id': 'approval-2',
      'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'command': 'echo hi'}})
assert read() == {'id': 'approval-2', 'result': {'decision': 'decline'}}
sys.stdin.readline()
""",
    )
    try:
        pending = await bridge.next_event(timeout=2)
        assert isinstance(pending, RequestPending)
        await bridge.cancel_pending()
        assert await bridge.next_event(timeout=2) == RequestFinished(
            pending.id, "cancelled"
        )
        assert not await bridge.answer_request(pending.id, "accept")
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_two_approvals_map_to_their_original_server_requests(
    tmp_path: Path,
) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
send({'method': 'item/commandExecution/requestApproval', 'id': 'command-rpc',
      'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'command': 'echo hi', 'cwd': 'C:\\private'}})
send({'method': 'item/fileChange/requestApproval', 'id': 'file-rpc',
      'params': {'threadId': 'thread-1', 'turnId': 'turn-1', 'reason': 'write proof', 'grantRoot': 'C:\\private'}})
responses = [read(), read()]
assert {'id': 'file-rpc', 'result': {'decision': 'accept'}} in responses
assert {'id': 'command-rpc', 'result': {'decision': 'decline'}} in responses
sys.stdin.readline()
""",
    )
    try:
        first = await bridge.next_event(timeout=2)
        second = await bridge.next_event(timeout=2)
        assert isinstance(first, RequestPending)
        assert isinstance(second, RequestPending)
        assert first.id != second.id
        assert (first.kind, second.kind) == ("command", "file_change")
        assert first.details == {"command": "echo hi"}
        assert second.details == {"reason": "write proof"}
        assert await bridge.answer_request(second.id, "accept")
        assert await bridge.answer_request(first.id, "decline")
        assert {
            await bridge.next_event(timeout=2),
            await bridge.next_event(timeout=2),
        } == {
            RequestFinished(first.id, "completed"),
            RequestFinished(second.id, "completed"),
        }
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
async def test_interrupt_retries_before_codex_marks_the_turn_active(tmp_path: Path) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
first = read()
assert first['method'] == 'turn/interrupt'
send({'id': first['id'], 'error': {'code': -32600, 'message': 'no active turn to interrupt'}})
second = read()
assert second['method'] == 'turn/interrupt'
assert second['params'] == first['params']
send({'id': second['id'], 'result': {}})
sys.stdin.readline()
""",
    )
    try:
        await bridge.interrupt_turn("thread-1", "turn-1")
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
assert resume['params'] == {'threadId': 'thread-1', 'excludeTurns': True, 'cwd': EXPECTED_CWD}
send({'id': resume['id'], 'result': {'thread': {'id': 'thread-1'}, 'cwd': EXPECTED_CWD}})
interrupt = read()
assert interrupt['method'] == 'turn/interrupt'
assert interrupt['params'] == {'threadId': 'thread-1', 'turnId': 'turn-1'}
send({'id': interrupt['id'], 'result': {}})
turn = read()
send({'id': turn['id'], 'error': {'code': -32000, 'message': 'turn rejected'}})
sys.stdin.readline()
""".replace("EXPECTED_CWD", repr(str(tmp_path))),
    )
    try:
        assert await bridge.resume_thread("thread-1", tmp_path) == "thread-1"
        await bridge.interrupt_turn("thread-1", "turn-1")
        with pytest.raises(OperationFailed, match="turn rejected"):
            await bridge.start_turn("thread-1", "hello")
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_resume_rejects_an_untrusted_effective_cwd(tmp_path: Path) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
resume = read()
assert resume['method'] == 'thread/resume'
send({'id': resume['id'], 'result': {'thread': {'id': 'thread-1'}, 'cwd': BAD_CWD}})
sys.stdin.readline()
""".replace("BAD_CWD", repr(str(tmp_path / "other"))),
    )
    try:
        with pytest.raises(OperationFailed, match="outside configured project"):
            await bridge.resume_thread("thread-1", tmp_path)
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_catalog_is_normalized_and_steer_uses_active_turn_id(
    tmp_path: Path,
) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
models = read()
assert models['method'] == 'model/list'
send({'id': models['id'], 'result': {'data': [
    {'id': 'first', 'model': 'runtime-first', 'displayName': 'First', 'hidden': False,
     'isDefault': True, 'defaultReasoningEffort': 'low',
     'supportedReasoningEfforts': [{'reasoningEffort': 'low', 'description': 'Fast'},
                                   {'reasoningEffort': 'high', 'description': 'Deep'}]},
    {'id': 'hidden', 'model': 'hidden', 'displayName': 'Hidden', 'hidden': True,
     'isDefault': False, 'defaultReasoningEffort': 'low', 'supportedReasoningEfforts': []}
], 'nextCursor': None}})
turn = read()
assert turn['method'] == 'turn/start'
assert turn['params']['model'] == 'runtime-first'
assert turn['params']['effort'] == 'high'
send({'id': turn['id'], 'result': {'turn': {'id': 'turn-1'}}})
steer = read()
assert steer['method'] == 'turn/steer'
assert steer['params'] == {'threadId': 'thread-1', 'expectedTurnId': 'turn-1',
                            'input': [{'type': 'text', 'text': 'change direction'}]}
send({'id': steer['id'], 'result': {'turnId': 'turn-1'}})
sys.stdin.readline()
""",
    )
    try:
        catalog = await bridge.list_models()
        assert [
            (model.id, model.model, model.reasoning_efforts) for model in catalog
        ] == [("first", "runtime-first", ("low", "high"))]
        assert (
            await bridge.start_turn(
                "thread-1", "hello", model="runtime-first", effort="high"
            )
            == "turn-1"
        )
        await bridge.steer_turn("thread-1", "turn-1", "change direction")
    finally:
        await bridge.close()


@pytest.mark.asyncio
async def test_model_catalog_pagination_and_optional_experimental_discovery(
    tmp_path: Path,
) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
first = read()
assert first['method'] == 'model/list' and first['params'] == {}
send({'id': first['id'], 'result': {'data': [
    {'id': 'one', 'model': 'one', 'displayName': 'One', 'hidden': False,
     'isDefault': False, 'defaultReasoningEffort': 'medium',
     'supportedReasoningEfforts': [{'reasoningEffort': 'medium'}]}
], 'nextCursor': 'next'}})
second = read()
assert second['method'] == 'model/list' and second['params'] == {'cursor': 'next'}
send({'id': second['id'], 'result': {'data': [
    {'id': 'two', 'model': 'two', 'displayName': 'Two', 'hidden': False,
     'isDefault': True, 'defaultReasoningEffort': 'low',
     'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}
], 'nextCursor': None}})
sys.stdin.readline()
""",
    )
    try:
        assert [model.id for model in await bridge.list_models()] == ["one", "two"]
        assert await bridge.list_collaboration_modes() == ()
    finally:
        await bridge.close()

    experimental = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
request = read()
assert request['method'] == 'collaborationMode/list'
send({'id': request['id'], 'error': {'code': -32601, 'message': 'Method not found'}})
sys.stdin.readline()
""",
        experimental_features=True,
    )
    try:
        assert await experimental.list_collaboration_modes() == ()
    finally:
        await experimental.close()


@pytest.mark.asyncio
async def test_read_messages_projects_persisted_codex_items(tmp_path: Path) -> None:
    bridge = await bridge_for(
        tmp_path,
        HANDSHAKE
        + """
request = read()
assert request['method'] == 'thread/read'
assert request['params'] == {'threadId': 'thread-1', 'includeTurns': True}
send({'id': request['id'], 'result': {'thread': {'turns': [
    {'items': [
        {'type': 'userMessage', 'content': [{'type': 'text', 'text': 'hello'}]},
        {'type': 'agentMessage', 'text': 'hi'},
        {'type': 'commandExecution', 'command': 'pwd'},
    ]},
]}}})
sys.stdin.readline()
""",
    )
    try:
        assert await bridge.read_messages("thread-1") == [
            {"role": "user", "text": "hello"},
            {"role": "assistant", "text": "hi"},
        ]
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
