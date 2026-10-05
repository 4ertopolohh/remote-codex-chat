from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from conftest import AuthenticatedTestClient as TestClient
from starlette.websockets import WebSocketDisconnect
from test_chat_websocket import FakeBridge
from test_conversation_recovery import FakeBridge as RecoveryBridge

from app import create_app
from codex_bridge import TurnCompleted


def configured(tmp_path: Path) -> list[dict[str, str]]:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    return [
        {"id": "first", "name": "First", "path": str(first)},
        {"id": "second", "name": "Second", "path": str(second)},
    ]


def test_project_list_and_selection_use_only_safe_metadata_and_trusted_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    projects = configured(tmp_path)
    monkeypatch.setenv("RC_PROJECTS", json.dumps(projects))
    bridge = FakeBridge()
    app = create_app(lambda: bridge, database=tmp_path / "conversations.sqlite3")
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "list_projects"})
        listed = ws.receive_json()
        assert listed == {"type": "project_list", "projects": [{"id": "first", "name": "First"}, {"id": "second", "name": "Second"}], "selected_id": "first"}
        assert str(tmp_path) not in json.dumps(listed)
        ws.send_json({"type": "select_project", "id": "second"})
        assert ws.receive_json() == {"type": "project_selected", "id": "second"}
        ws.send_json({"type": "new_conversation"})
        selected = ws.receive_json()
        assert selected["conversation"]["project_id"] == "second"
        assert bridge.project == (tmp_path / "second").resolve()
        assert str(tmp_path) not in json.dumps(selected)
        ws.send_json({"type": "list_conversations"})
        assert [item["id"] for item in ws.receive_json()["conversations"]] == [selected["conversation"]["id"]]
        ws.send_json({"type": "select_project", "id": "first"})
        assert ws.receive_json() == {"type": "project_selected", "id": "first"}
        ws.send_json({"type": "select_conversation", "id": selected["conversation"]["id"]})
        assert ws.receive_json() == {"type": "error", "code": "conversation_not_found"}
        ws.send_json({"type": "list_conversations"})
        assert ws.receive_json()["conversations"] == []


def test_unknown_and_path_like_project_ids_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RC_PROJECTS", json.dumps(configured(tmp_path)))
    with TestClient(create_app(lambda: FakeBridge(), database=tmp_path / "db.sqlite3")) as client, client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json() == {"type": "ready"}
        for bad in ("missing", "../first", "C:\\tmp", "/tmp"):
            ws.send_json({"type": "select_project", "id": bad})
            assert ws.receive_json() == {"type": "error", "code": "project_not_found"}
        ws.send_json({"type": "new_conversation", "cwd": str(tmp_path)})
        assert ws.receive_json() == {"type": "error", "code": "invalid_message"}
        ws.send_json({"type": "submit_prompt", "text": "work", "cwd": str(tmp_path)})
        assert ws.receive_json() == {"type": "error", "code": "invalid_message"}


def test_missing_configured_directory_returns_controlled_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RC_PROJECTS", json.dumps([{"id": "gone", "name": "Gone", "path": str(tmp_path / "gone") }]))
    with TestClient(create_app(lambda: FakeBridge(), database=tmp_path / "db.sqlite3")) as client, client.websocket_connect("/ws/chat") as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "new_conversation"})
        assert ws.receive_json() == {"type": "error", "code": "project_unavailable"}


def test_removed_project_blocks_resuming_its_conversation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RC_PROJECTS", json.dumps(configured(tmp_path)))
    threads: set[str] = set()
    with (
        TestClient(create_app(lambda: RecoveryBridge(threads), database=tmp_path / "db.sqlite3")) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "new_conversation"})
        conversation_id = ws.receive_json()["conversation"]["id"]
        (tmp_path / "first").rmdir()
        ws.send_json({"type": "select_conversation", "id": conversation_id})
        assert ws.receive_json() == {"type": "error", "code": "project_unavailable"}


def test_invalid_configurations_fail_before_serving(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [
        [{"id": "../evil", "name": "Evil", "path": str(tmp_path)}],
        [{"id": "same", "name": "One", "path": str(tmp_path)}, {"id": "same", "name": "Two", "path": str(tmp_path)}],
        [{"id": "relative", "name": "Relative", "path": "./project"}],
        [{"id": "private", "name": str(tmp_path), "path": str(tmp_path)}],
    ]
    for case in cases:
        monkeypatch.setenv("RC_PROJECTS", json.dumps(case))
        with pytest.raises(ValueError):
            create_app(lambda: FakeBridge(), database=tmp_path / "db.sqlite3")


def test_only_one_connection_can_run_a_turn_for_project(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = create_app(lambda: bridge, project=tmp_path, database=tmp_path / "db.sqlite3")
    with TestClient(app) as client, client.websocket_connect("/ws/chat") as first:
        assert first.receive_json() == {"type": "ready"}
        first.send_json({"type": "submit_prompt", "text": "work"})
        assert first.receive_json()["type"] == "conversation_selected"
        assert first.receive_json() == {"type": "turn_started"}
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws/chat") as second,
        ):
            second.receive_json()
        assert bridge.prompts == ["work"]


def test_disconnect_holds_connection_until_turn_finishes(tmp_path: Path) -> None:
    bridge = FakeBridge()
    app = create_app(lambda: bridge, project=tmp_path, database=tmp_path / "db.sqlite3")
    with TestClient(app) as client:
        with client.websocket_connect("/ws/chat") as first:
            assert first.receive_json() == {"type": "ready"}
            first.send_json({"type": "submit_prompt", "text": "work"})
            assert first.receive_json()["type"] == "conversation_selected"
            assert first.receive_json() == {"type": "turn_started"}
        with (
            pytest.raises(WebSocketDisconnect),
            client.websocket_connect("/ws/chat") as second,
        ):
            second.receive_json()
        bridge.events.put_nowait(TurnCompleted("thread-1", "turn-1", "interrupted"))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                with client.websocket_connect("/ws/chat") as third:
                    assert third.receive_json() == {"type": "ready"}
                break
            except WebSocketDisconnect:
                time.sleep(0.01)
        else:
            pytest.fail("Turn completion did not release the connection")


def test_selected_project_conversation_survives_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RC_PROJECTS", json.dumps(configured(tmp_path)))
    db = tmp_path / "db.sqlite3"
    threads: set[str] = set()
    with (
        TestClient(create_app(lambda: RecoveryBridge(threads), database=db)) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "select_project", "id": "second"})
        assert ws.receive_json() == {"type": "project_selected", "id": "second"}
        ws.send_json({"type": "new_conversation"})
        conversation = ws.receive_json()["conversation"]
        assert conversation["project_id"] == "second"

    bridge = RecoveryBridge(threads)
    with (
        TestClient(create_app(lambda: bridge, database=db)) as client,
        client.websocket_connect("/ws/chat") as ws,
    ):
        assert ws.receive_json() == {"type": "ready"}
        ws.send_json({"type": "select_project", "id": "second"})
        assert ws.receive_json() == {"type": "project_selected", "id": "second"}
        ws.send_json({"type": "list_conversations"})
        assert [item["id"] for item in ws.receive_json()["conversations"]] == [
            conversation["id"]
        ]
        ws.send_json({"type": "select_conversation", "id": conversation["id"]})
        assert ws.receive_json()["conversation"]["project_id"] == "second"
    assert bridge.resumed == ["thread-1"]
