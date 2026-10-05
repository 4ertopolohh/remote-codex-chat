from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from conftest import AuthenticatedTestClient as TestClient
from starlette.websockets import WebSocketDisconnect

from app import create_app
from codex_bridge import (
    AgentMessageDelta,
    CollaborationCapability,
    ModelCapability,
    OperationFailed,
    RequestFinished,
    RequestPending,
    ThreadStatusChanged,
    TurnCompleted,
    UsageChanged,
)


class FakeBridge:
    def __init__(self) -> None:
        self.ready = False
        self.events: asyncio.Queue = asyncio.Queue()
        self.project: Path | None = None
        self.prompts: list[str] = []
        self.interrupted: list[tuple[str, str]] = []
        self.steered: list[str] = []
        self.models = (
            ModelCapability(
                "first", "runtime-first", "First", ("low", "high"), "low", True
            ),
        )
        self.modes: tuple[CollaborationCapability, ...] = ()
        self.stop_error = False
        self.user_input_supported = False
        self.pending: set[str] = set()
        self.answers: list[tuple[str, str]] = []
        self.usage: dict[str, object] | None = None
        self.usage_error = False
        self.usage_updates: asyncio.Queue[UsageChanged] = asyncio.Queue()

    async def start(self) -> None:
        self.ready = True

    async def close(self) -> None:
        self.ready = False

    async def start_thread(self, project: Path) -> str:
        self.project = project
        return "thread-1"

    async def start_turn(
        self, thread_id: str, prompt: str, **options: str | None
    ) -> str:
        self.prompts.append(prompt)
        self.options = options
        return "turn-1"

    async def list_models(self) -> tuple[ModelCapability, ...]:
        return self.models

    async def list_collaboration_modes(self) -> tuple[CollaborationCapability, ...]:
        return self.modes

    async def read_usage(self) -> dict[str, object]:
        if self.usage_error:
            raise OperationFailed("usage read failed")
        return self.usage or {"status": "unsupported", "rate_limits": None, "rate_limits_by_id": {}, "ordinary_usage_allowed": None}

    async def next_usage_update(self) -> UsageChanged:
        return await self.usage_updates.get()


    async def steer_turn(self, thread_id: str, turn_id: str, prompt: str) -> None:
        self.steered.append(prompt)

    async def next_event(self) -> object:
        return await self.events.get()

    async def interrupt_turn(self, thread_id: str, turn_id: str) -> None:
        if self.stop_error:
            raise OperationFailed("stop rejected")
        self.interrupted.append((thread_id, turn_id))

    async def answer_request(self, pending_id: str, decision: str) -> bool:
        if pending_id not in self.pending:
            return False
        self.pending.remove(pending_id)
        self.answers.append((pending_id, decision))
        self.events.put_nowait(RequestFinished(pending_id, "completed"))
        return True

    async def answer_user_input(
        self, pending_id: str, answers: dict[str, list[str]]
    ) -> bool:
        return False

    async def cancel_pending(self) -> None:
        for pending_id in tuple(self.pending):
            await self.cancel_request(pending_id)

    async def cancel_request(self, pending_id: str) -> None:
        if pending_id in self.pending:
            self.pending.remove(pending_id)
            self.answers.append((pending_id, "decline"))
            self.events.put_nowait(RequestFinished(pending_id, "cancelled"))


def test_usage_read_is_isolated_from_chat(tmp_path: Path) -> None:
    bridge = FakeBridge()
    bridge.usage_error = True
    app = create_app(lambda: bridge, project=tmp_path, database=tmp_path / "conversations.sqlite3")
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "read_usage"})
        assert ws.receive_json() == {"type": "usage", "status": "error", "rate_limits": None, "rate_limits_by_id": {}, "ordinary_usage_allowed": None}
        ws.send_json({"type": "submit_prompt", "text": "hello"})
        assert ws.receive_json()["type"] == "conversation_selected"
        assert ws.receive_json() == {"type": "turn_started"}


def test_usage_read_preserves_flexible_sparse_data(tmp_path: Path) -> None:
    bridge = FakeBridge()
    bridge.usage = {"status": "available", "rate_limits": None, "rate_limits_by_id": {"new_bucket": {"primary": {"used_percent": 42.0}}}, "ordinary_usage_allowed": None}
    app = create_app(lambda: bridge, project=tmp_path, database=tmp_path / "conversations.sqlite3")
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "read_usage"})
        assert ws.receive_json() == {"type": "usage", **bridge.usage}


def test_usage_update_during_turn_does_not_interrupt_stream(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = create_app(lambda: bridge, project=tmp_path, database=tmp_path / "conversations.sqlite3")
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "submit_prompt", "text": "hello"})
        assert ws.receive_json()["type"] == "conversation_selected"
        assert ws.receive_json() == {"type": "turn_started"}
        bridge.usage_updates.put_nowait(UsageChanged({"limit_id": "dynamic", "primary": {"used_percent": 20}}))
        bridge.events.put_nowait(AgentMessageDelta("thread-1", "turn-1", "hi"))
        received = [ws.receive_json(), ws.receive_json()]
        assert {"type": "usage_update", "rate_limits": {"limit_id": "dynamic", "primary": {"used_percent": 20}}} in received
        assert {"type": "assistant_delta", "text": "hi"} in received


def test_usage_update_is_delivered_while_idle(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = create_app(lambda: bridge, project=tmp_path, database=tmp_path / "conversations.sqlite3")
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json() == {"type": "ready"}
        bridge.usage_updates.put_nowait(UsageChanged({"limit_id": "fresh", "primary": {"used_percent": 30}}))
        assert ws.receive_json() == {"type": "usage_update", "rate_limits": {"limit_id": "fresh", "primary": {"used_percent": 30}}}


def test_prompt_streams_domain_events_and_completion(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = create_app(
        lambda: bridge, project=tmp_path, database=tmp_path / "conversations.sqlite3"
    )
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "submit_prompt", "text": "hello"})
        assert ws.receive_json()["type"] == "conversation_selected"
        assert ws.receive_json() == {"type": "turn_started"}
        bridge.events.put_nowait(ThreadStatusChanged("thread-1", "active"))
        bridge.events.put_nowait(AgentMessageDelta("thread-1", "turn-1", "hi"))
        bridge.events.put_nowait(AgentMessageDelta("thread-1", "turn-1", " there"))
        bridge.events.put_nowait(TurnCompleted("thread-1", "turn-1", "completed"))
        assert ws.receive_json() == {"type": "agent_status", "status": "active"}
        assert ws.receive_json() == {"type": "assistant_delta", "text": "hi"}
        assert ws.receive_json() == {"type": "assistant_delta", "text": " there"}
        assert ws.receive_json() == {"type": "turn_completed", "status": "completed"}
    assert bridge.project == tmp_path
    assert bridge.prompts == ["hello"]


def test_next_prompt_is_received_after_turn_completion(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = create_app(lambda: bridge, project=tmp_path, database=tmp_path / "conversations.sqlite3")
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "submit_prompt", "text": "first"})
        assert ws.receive_json()["type"] == "conversation_selected"
        assert ws.receive_json() == {"type": "turn_started"}
        bridge.events.put_nowait(TurnCompleted("thread-1", "turn-1", "completed"))
        assert ws.receive_json() == {"type": "turn_completed", "status": "completed"}
        assert ws.receive_json()["type"] == "conversation_list"
        ws.send_json({"type": "submit_prompt", "text": "second"})
        deadline = time.monotonic() + 0.5
        while len(bridge.prompts) < 2 and time.monotonic() < deadline:
            time.sleep(0.01)
        assert bridge.prompts == ["first", "second"]
        assert ws.receive_json() == {"type": "turn_started"}


def test_approval_is_visible_once_and_unknown_id_is_rejected(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = create_app(
        lambda: bridge, project=tmp_path, database=tmp_path / "chat.sqlite3"
    )
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "submit_prompt", "text": "hello"})
        ws.receive_json()
        assert ws.receive_json() == {"type": "turn_started"}
        bridge.pending.add("opaque-1")
        bridge.events.put_nowait(
            RequestPending(
                "opaque-1", "thread-1", "turn-1", "command", {"command": "echo hi"}
            )
        )
        assert ws.receive_json() == {
            "type": "pending_request",
            "id": "opaque-1",
            "kind": "command",
            "details": {"command": "echo hi"},
        }
        ws.send_json(
            {"type": "answer_approval", "id": "invented", "decision": "accept"}
        )
        assert ws.receive_json() == {"type": "error", "code": "request_unavailable"}
        ws.send_json(
            {"type": "answer_approval", "id": "opaque-1", "decision": "accept"}
        )
        assert ws.receive_json() == {
            "type": "request_outcome",
            "id": "opaque-1",
            "status": "completed",
        }
        ws.send_json(
            {"type": "answer_approval", "id": "opaque-1", "decision": "decline"}
        )
        assert ws.receive_json() == {"type": "error", "code": "request_unavailable"}
        assert bridge.answers == [("opaque-1", "accept")]


def test_disconnect_declines_pending_approval(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = create_app(
        lambda: bridge, project=tmp_path, database=tmp_path / "chat.sqlite3"
    )
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()
            ws.send_json({"type": "submit_prompt", "text": "hello"})
            ws.receive_json()
            ws.receive_json()
            bridge.pending.add("opaque-2")
            bridge.events.put_nowait(
                RequestPending(
                    "opaque-2", "thread-1", "turn-1", "file_change", {"reason": "write"}
                )
            )
            assert ws.receive_json()["kind"] == "file_change"
        for _ in range(100):
            if bridge.answers:
                break
            time.sleep(0.01)
        assert bridge.answers == [("opaque-2", "decline")]


def test_request_from_other_turn_is_cancelled_without_browser_authority(
    tmp_path: Path,
) -> None:
    bridge = FakeBridge()
    app = create_app(
        lambda: bridge, project=tmp_path, database=tmp_path / "chat.sqlite3"
    )
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        ws.receive_json()
        ws.send_json({"type": "submit_prompt", "text": "hello"})
        ws.receive_json()
        ws.receive_json()
        bridge.pending.add("stale")
        bridge.events.put_nowait(
            RequestPending(
                "stale", "thread-1", "old-turn", "command", {"command": "echo hi"}
            )
        )
        ws.send_json({"type": "answer_approval", "id": "stale", "decision": "accept"})
        assert ws.receive_json() == {"type": "error", "code": "request_unavailable"}
        for _ in range(100):
            if bridge.answers:
                break
            time.sleep(0.01)
        assert bridge.answers == [("stale", "decline")]


def test_rejects_malformed_messages_and_recovers(tmp_path: Path) -> None:
    bridge = FakeBridge()
    with (
        TestClient(
            create_app(
                lambda: bridge,
                project=tmp_path,
                database=tmp_path / "conversations.sqlite3",
            )
        ) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        assert ws.receive_json() == {"type": "ready"}
        for message in (
            {"type": "submit_prompt", "text": ""},
            {"type": "submit_prompt", "text": "hi", "cwd": "C:\\"},
            {"type": "rpc", "method": "thread/start"},
        ):
            ws.send_json(message)
            assert ws.receive_json() == {"type": "error", "code": "invalid_message"}
        ws.send_bytes(b"not a JSON text frame")
        assert ws.receive_json() == {"type": "error", "code": "invalid_message"}
        ws.send_json({"type": "submit_prompt", "text": "valid"})
        assert ws.receive_json()["type"] == "conversation_selected"
        assert ws.receive_json() == {"type": "turn_started"}
        ws.send_json({"type": "rpc", "method": "thread/start"})
        assert ws.receive_json() == {"type": "error", "code": "invalid_message"}
        ws.send_json({"type": "submit_prompt", "text": "another"})
        assert ws.receive_json() == {"type": "error", "code": "turn_in_progress"}
        bridge.events.put_nowait(TurnCompleted("thread-1", "turn-1", "failed"))
        assert ws.receive_json() == {"type": "turn_completed", "status": "failed"}


def test_disconnect_interrupts_active_turn(tmp_path: Path) -> None:
    bridge = FakeBridge()
    with TestClient(
        create_app(
            lambda: bridge,
            project=tmp_path,
            database=tmp_path / "conversations.sqlite3",
        )
    ) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()
            ws.send_json({"type": "submit_prompt", "text": "hello"})
            assert ws.receive_json()["type"] == "conversation_selected"
            assert ws.receive_json() == {"type": "turn_started"}
        for _ in range(100):
            if bridge.interrupted:
                break
            time.sleep(0.01)
        assert bridge.interrupted == [("thread-1", "turn-1")]


def test_app_server_crash_while_draining_releases_chat_for_reconnect(tmp_path: Path) -> None:
    class CrashingBridge(FakeBridge):
        async def next_event(self) -> object:
            event = await self.events.get()
            if isinstance(event, Exception):
                raise event
            return event

    bridge = CrashingBridge()
    app = create_app(lambda: bridge, project=tmp_path, database=tmp_path / "chat.sqlite3")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()
            ws.send_json({"type": "submit_prompt", "text": "may have run"})
            ws.receive_json()
            assert ws.receive_json() == {"type": "turn_started"}
        bridge.events.put_nowait(OperationFailed("app-server terminated"))
        for _ in range(100):
            try:
                with client.websocket_connect("/ws/chat") as reconnected:
                    assert reconnected.receive_json() == {"type": "ready"}
                break
            except WebSocketDisconnect:
                time.sleep(0.01)
        else:
            pytest.fail("chat remained locked after app-server crash")


def test_replayed_submission_id_does_not_start_a_second_turn_after_restart(tmp_path: Path) -> None:
    class ResumableBridge(FakeBridge):
        async def resume_thread(self, thread_id: str, project: Path) -> str:
            return thread_id

        async def read_messages(self, thread_id: str) -> list[dict[str, str]]:
            return [{"role": "user", "text": "once"}]

    database = tmp_path / "chat.sqlite3"
    first_bridge = ResumableBridge()
    with (
        TestClient(create_app(lambda: first_bridge, project=tmp_path, database=database)) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
            ws.receive_json()
            ws.send_json({"type": "new_conversation"})
            conversation_id = ws.receive_json()["conversation"]["id"]
            ws.send_json({"type": "submit_prompt", "text": "once", "request_id": "request-1"})
            assert ws.receive_json() == {"type": "turn_started"}
            first_bridge.events.put_nowait(TurnCompleted("thread-1", "turn-1", "completed"))
            assert ws.receive_json() == {"type": "turn_completed", "status": "completed"}
    second_bridge = ResumableBridge()
    with (
        TestClient(create_app(lambda: second_bridge, project=tmp_path, database=database)) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
            ws.receive_json()
            ws.send_json({"type": "select_conversation", "id": conversation_id})
            assert ws.receive_json()["type"] == "conversation_selected"
            ws.send_json({"type": "submit_prompt", "text": "once", "request_id": "request-1"})
            assert ws.receive_json() == {"type": "error", "code": "duplicate_submission"}
    assert first_bridge.prompts == ["once"]
    assert second_bridge.prompts == []


def test_unavailable_bridge_does_not_report_ready(tmp_path: Path) -> None:
    bridge = FakeBridge()
    with TestClient(
        create_app(
            lambda: bridge,
            project=tmp_path,
            database=tmp_path / "conversations.sqlite3",
        )
    ) as client:
        bridge.ready = False
        with client.websocket_connect("/ws/chat") as ws:
            assert ws.receive_json() == {"type": "error", "code": "codex_unavailable"}


def test_capability_validation_stop_and_steer(tmp_path: Path) -> None:
    bridge = FakeBridge()
    with (
        TestClient(
            create_app(
                lambda: bridge, project=tmp_path, database=tmp_path / "chat.sqlite3"
            )
        ) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "list_capabilities"})
        capabilities = ws.receive_json()
        assert capabilities["type"] == "capabilities"
        assert capabilities["models"][0]["id"] == "first"
        ws.send_json({"type": "steer_turn", "text": "too early"})
        assert ws.receive_json() == {"type": "error", "code": "no_active_turn"}
        ws.send_json({"type": "submit_prompt", "text": "hello", "model_id": "missing"})
        assert ws.receive_json() == {"type": "error", "code": "model_unavailable"}
        assert ws.receive_json()["type"] == "capabilities"
        ws.send_json(
            {
                "type": "submit_prompt",
                "text": "hello",
                "model_id": "first",
                "reasoning_effort": "wrong",
            }
        )
        assert ws.receive_json() == {"type": "error", "code": "reasoning_unavailable"}
        assert ws.receive_json()["type"] == "capabilities"
        ws.send_json(
            {
                "type": "submit_prompt",
                "text": "hello",
                "model_id": "first",
                "reasoning_effort": "high",
            }
        )
        assert ws.receive_json()["type"] == "conversation_selected"
        assert ws.receive_json() == {"type": "turn_started"}
        assert bridge.options["model"] == "runtime-first"
        assert bridge.options["effort"] == "high"
        ws.send_json({"type": "steer_turn", "text": "change direction"})
        assert ws.receive_json() == {
            "type": "steer_accepted",
            "text": "change direction",
        }
        assert bridge.steered == ["change direction"]
        ws.send_json({"type": "stop_turn"})
        assert ws.receive_json() == {"type": "agent_status", "status": "stopping"}
        assert bridge.interrupted == [("thread-1", "turn-1")]
        bridge.events.put_nowait(TurnCompleted("thread-1", "turn-1", "interrupted"))
        assert ws.receive_json() == {"type": "turn_completed", "status": "interrupted"}


def test_experimental_mode_hidden_without_opt_in(tmp_path: Path) -> None:
    bridge = FakeBridge()
    with (
        TestClient(
            create_app(
                lambda: bridge, project=tmp_path, database=tmp_path / "chat.sqlite3"
            )
        ) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        ws.receive_json()
        ws.send_json(
            {"type": "submit_prompt", "text": "hello", "collaboration_mode": "plan"}
        )
        assert ws.receive_json() == {
            "type": "error",
            "code": "collaboration_unavailable",
        }


def test_experimental_mode_requires_runtime_discovery(tmp_path: Path) -> None:
    bridge = FakeBridge()
    bridge.modes = (CollaborationCapability("Plan", "plan", None, "medium"),)
    with (
        TestClient(
            create_app(
                lambda: bridge,
                project=tmp_path,
                database=tmp_path / "chat.sqlite3",
                experimental_features=True,
            )
        ) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        ws.receive_json()
        ws.send_json({"type": "list_capabilities"})
        assert ws.receive_json()["collaboration_modes"][0]["mode"] == "plan"
        ws.send_json(
            {
                "type": "submit_prompt",
                "text": "plan this",
                "model_id": "first",
                "collaboration_mode": "plan",
            }
        )
        assert ws.receive_json()["type"] == "conversation_selected"
        assert ws.receive_json() == {"type": "turn_started"}
        assert bridge.options["collaboration_mode"] == "plan"


def test_normal_chat_survives_missing_experimental_modes(tmp_path: Path) -> None:
    bridge = FakeBridge()
    with (
        TestClient(
            create_app(
                lambda: bridge,
                project=tmp_path,
                database=tmp_path / "chat.sqlite3",
                experimental_features=True,
            )
        ) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        ws.receive_json()
        ws.send_json({"type": "list_capabilities"})
        assert ws.receive_json()["collaboration_modes"] == []
        ws.send_json({"type": "submit_prompt", "text": "hello", "model_id": "first"})
        assert ws.receive_json()["type"] == "conversation_selected"
        assert ws.receive_json() == {"type": "turn_started"}


def test_failed_stop_keeps_turn_active_and_allows_steer(tmp_path: Path) -> None:
    bridge = FakeBridge()
    bridge.stop_error = True
    with (
        TestClient(
            create_app(
                lambda: bridge, project=tmp_path, database=tmp_path / "chat.sqlite3"
            )
        ) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        ws.receive_json()
        ws.send_json({"type": "submit_prompt", "text": "hello"})
        ws.receive_json()
        assert ws.receive_json() == {"type": "turn_started"}
        ws.send_json({"type": "stop_turn"})
        assert ws.receive_json() == {"type": "error", "code": "stop_failed"}
        ws.send_json({"type": "steer_turn", "text": "continue"})
        assert ws.receive_json() == {"type": "steer_accepted", "text": "continue"}


def test_experimental_preset_applies_when_effort_not_explicit(tmp_path: Path) -> None:
    bridge = FakeBridge()
    bridge.models = bridge.models + (
        ModelCapability("second", "runtime-second", "Second", ("high",), "high", False),
    )
    bridge.modes = (CollaborationCapability("Plan", "plan", "runtime-second", "high"),)
    with (
        TestClient(
            create_app(
                lambda: bridge,
                project=tmp_path,
                database=tmp_path / "chat.sqlite3",
                experimental_features=True,
            )
        ) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        ws.receive_json()
        ws.send_json(
            {"type": "submit_prompt", "text": "plan", "collaboration_mode": "plan"}
        )
        ws.receive_json()
        assert ws.receive_json() == {"type": "turn_started"}
        assert bridge.options["effort"] == "high"
        assert bridge.options["model"] == "runtime-second"
