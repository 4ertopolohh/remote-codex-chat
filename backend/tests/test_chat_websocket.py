from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app import create_app
from codex_bridge import AgentMessageDelta, ThreadStatusChanged, TurnCompleted
from fastapi.testclient import TestClient


class FakeBridge:
    def __init__(self) -> None:
        self.ready = False
        self.events: asyncio.Queue = asyncio.Queue()
        self.project: Path | None = None
        self.prompts: list[str] = []
        self.interrupted: list[tuple[str, str]] = []

    async def start(self) -> None:
        self.ready = True

    async def close(self) -> None:
        self.ready = False

    async def start_thread(self, project: Path) -> str:
        self.project = project
        return "thread-1"

    async def start_turn(self, thread_id: str, prompt: str) -> str:
        self.prompts.append(prompt)
        return "turn-1"

    async def next_event(self) -> object:
        return await self.events.get()

    async def interrupt_turn(self, thread_id: str, turn_id: str) -> None:
        self.interrupted.append((thread_id, turn_id))


def test_prompt_streams_domain_events_and_completion(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = create_app(lambda: bridge, project=tmp_path)
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "submit_prompt", "text": "hello"})
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


def test_rejects_malformed_messages_and_recovers(tmp_path: Path) -> None:
    bridge = FakeBridge()
    with (
        TestClient(create_app(lambda: bridge, project=tmp_path)) as client,
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
        assert ws.receive_json() == {"type": "turn_started"}
        bridge.events.put_nowait(TurnCompleted("thread-1", "turn-1", "failed"))
        assert ws.receive_json() == {"type": "turn_completed", "status": "failed"}


def test_disconnect_interrupts_active_turn(tmp_path: Path) -> None:
    bridge = FakeBridge()
    with TestClient(create_app(lambda: bridge, project=tmp_path)) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()
            ws.send_json({"type": "submit_prompt", "text": "hello"})
            assert ws.receive_json() == {"type": "turn_started"}
        for _ in range(100):
            if bridge.interrupted:
                break
            time.sleep(0.01)
        assert bridge.interrupted == [("thread-1", "turn-1")]


def test_unavailable_bridge_does_not_report_ready(tmp_path: Path) -> None:
    bridge = FakeBridge()
    with TestClient(create_app(lambda: bridge, project=tmp_path)) as client:
        bridge.ready = False
        with client.websocket_connect("/ws/chat") as ws:
            assert ws.receive_json() == {"type": "error", "code": "codex_unavailable"}
