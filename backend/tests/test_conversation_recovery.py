from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from conftest import AuthenticatedTestClient as TestClient

from app import create_app
from codex_bridge import ModelCapability, OperationFailed
from conversation_store import ConversationStore


class FakeBridge:
    def __init__(self, threads: set[str]) -> None:
        self.ready = False
        self.threads = threads
        self.resumed: list[str] = []
        self.turns: list[tuple[str, str]] = []
        self.user_input_supported = False

    async def start(self) -> None:
        self.ready = True

    async def close(self) -> None:
        self.ready = False

    async def start_thread(self, project: Path) -> str:
        thread_id = f"thread-{len(self.threads) + 1}"
        self.threads.add(thread_id)
        return thread_id

    async def resume_thread(self, thread_id: str, project: Path) -> str:
        if thread_id not in self.threads:
            raise OperationFailed("thread not found")
        self.resumed.append(thread_id)
        return thread_id

    async def read_messages(self, thread_id: str) -> list[dict[str, str]]:
        return [{"role": "user", "text": "earlier prompt"}] if self.turns else []

    async def start_turn(
        self, thread_id: str, prompt: str, **options: str | None
    ) -> str:
        self.turns.append((thread_id, prompt))
        return "turn-1"

    async def list_models(self) -> tuple[ModelCapability, ...]:
        return ()

    async def next_event(self) -> object:
        await asyncio.Future()

    async def interrupt_turn(self, thread_id: str, turn_id: str) -> None:
        pass

    async def cancel_pending(self) -> None:
        pass


def test_existing_conversation_database_migrates_without_losing_history(tmp_path: Path) -> None:
    database = tmp_path / "conversations.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute("""CREATE TABLE conversations (
            id TEXT PRIMARY KEY, project_id TEXT NOT NULL, thread_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        connection.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
            ("saved", "default", "thread-1", "Earlier", "2026-01-01", "2026-01-01"),
        )
        connection.execute("PRAGMA user_version = 1")
    store = ConversationStore(database)
    store.initialize()
    assert store.get("saved", "default").title == "Earlier"
    assert store.claim_submission("request-1", "saved")
    assert not store.claim_submission("request-1", "saved")


def test_conversation_survives_backend_restart_and_resumes(tmp_path: Path) -> None:
    db = tmp_path / "conversations.sqlite3"
    threads: set[str] = set()
    first = FakeBridge(threads)
    with (
        TestClient(create_app(lambda: first, project=tmp_path, database=db)) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "new_conversation"})
        selected = ws.receive_json()
        assert selected["type"] == "conversation_selected"
        conversation_id = selected["conversation"]["id"]
        assert selected["messages"] == []
        ws.send_json({"type": "submit_prompt", "text": "first prompt"})
        assert ws.receive_json() == {"type": "turn_started"}

    second = FakeBridge(threads)
    second.turns = first.turns.copy()
    with (
        TestClient(create_app(lambda: second, project=tmp_path, database=db)) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "list_conversations"})
        listed = ws.receive_json()
        assert listed["type"] == "conversation_list"
        assert [item["id"] for item in listed["conversations"]] == [conversation_id]
        assert listed["conversations"][0]["title"] == "first prompt"
        ws.send_json({"type": "select_conversation", "id": conversation_id})
        selected = ws.receive_json()
        assert selected["type"] == "conversation_selected"
        assert selected["messages"] == [{"role": "user", "text": "earlier prompt"}]
        ws.send_json({"type": "submit_prompt", "text": "continue"})
        assert ws.receive_json() == {"type": "turn_started"}
    assert second.resumed == ["thread-1"]
    assert second.turns == [("thread-1", "first prompt"), ("thread-1", "continue")]


def test_missing_codex_thread_reports_controlled_error(tmp_path: Path) -> None:
    db = tmp_path / "conversations.sqlite3"
    threads: set[str] = set()
    with (
        TestClient(
            create_app(lambda: FakeBridge(threads), project=tmp_path, database=db)
        ) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        ws.receive_json()
        ws.send_json({"type": "new_conversation"})
        conversation_id = ws.receive_json()["conversation"]["id"]
    threads.clear()
    with (
        TestClient(
            create_app(lambda: FakeBridge(threads), project=tmp_path, database=db)
        ) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        ws.receive_json()
        ws.send_json({"type": "select_conversation", "id": conversation_id})
        assert ws.receive_json() == {"type": "error", "code": "thread_unavailable"}


def test_new_conversation_has_independent_thread_and_reload_selects_it(
    tmp_path: Path,
) -> None:
    bridge = FakeBridge(set())
    app = create_app(
        lambda: bridge, project=tmp_path, database=tmp_path / "conversations.sqlite3"
    )
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as ws:
            ws.receive_json()
            ws.send_json({"type": "new_conversation"})
            first = ws.receive_json()["conversation"]["id"]
            ws.send_json({"type": "new_conversation"})
            second = ws.receive_json()["conversation"]["id"]
            assert first != second
            assert bridge.threads == {"thread-1", "thread-2"}
        with client.websocket_connect("/ws/chat") as ws:
            assert ws.receive_json() == {"type": "ready"}
            ws.send_json({"type": "select_conversation", "id": first})
            assert ws.receive_json()["conversation"]["id"] == first
            assert bridge.resumed == ["thread-1"]
