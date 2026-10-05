from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from test_chat_websocket import FakeBridge

from app import create_app
from config_store import ConfigStore, Configuration
from projects import Project


def test_configuration_survives_restart_without_legacy_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    password = "durable-secret"
    hashed = PasswordHasher().hash(password)
    first = tmp_path / "one"
    second = tmp_path / "two"
    first.mkdir()
    second.mkdir()
    store = ConfigStore(tmp_path / "config.sqlite3")
    store.bootstrap(Configuration(hashed, "local", "http://127.0.0.1:8765",
                                  [Project("one", "One", first), Project("two", "Two", second)]))
    monkeypatch.setenv("RC_CONFIG_DATABASE_PATH", str(store.path))
    for name in ("RC_PASSWORD_HASH", "RC_PROJECTS", "RC_PROJECT_PATH", "RC_AUTH_MODE", "RC_PUBLIC_ORIGIN"):
        monkeypatch.delenv(name, raising=False)
    for _ in range(2):
        with TestClient(create_app(lambda: FakeBridge(), database=tmp_path / "conversations.sqlite3")) as client:
            response = client.post("/auth/login", json={"password": password}, headers={"Origin": "http://127.0.0.1:8765"})
            assert response.status_code == 200
            assert client.post("/auth/login", json={"password": "wrong"}, headers={"Origin": "http://127.0.0.1:8765"}).status_code == 401
            with client.websocket_connect("/ws/chat", headers={"Origin": "http://127.0.0.1:8765"}) as ws:
                assert ws.receive_json() == {"type": "ready"}
                ws.send_json({"type": "list_projects"})
                listed = ws.receive_json()
                assert [p["id"] for p in listed["projects"]] == ["one", "two"]
                assert str(tmp_path) not in str(listed)
    assert password.encode() not in store.path.read_bytes()
    assert store.load().password_hash.startswith("$argon2id$")


def test_config_validation_and_schema(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.sqlite3")
    store.initialize()
    with sqlite3.connect(store.path) as db:
        db.execute("PRAGMA user_version = 2")
    with pytest.raises(ValueError, match="schema version"):
        store.load()


def test_unversioned_existing_schema_is_not_rewritten(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.sqlite3")
    with sqlite3.connect(store.path) as db:
        db.execute("CREATE TABLE settings (broken TEXT)")
    with pytest.raises(ValueError, match="unversioned schema"):
        store.load()


def test_incomplete_and_invalid_hash_fail_closed(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.sqlite3")
    store.initialize()
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO settings VALUES ('password_hash', 'invalid')")
    with pytest.raises(ValueError, match="incomplete"):
        store.load()
    with sqlite3.connect(store.path) as db:
        db.execute("INSERT INTO settings VALUES ('mode', 'local')")
        db.execute("INSERT INTO settings VALUES ('origin', 'http://127.0.0.1:8765')")
        db.execute("INSERT INTO projects VALUES ('one', 'One', ?, 0)", (str(tmp_path),))
    with pytest.raises(ValueError, match="Argon2id"):
        store.load()


def test_legacy_import_is_one_time(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RC_CONFIG_DATABASE_PATH", str(tmp_path / "config.sqlite3"))
    monkeypatch.setenv("RC_PASSWORD_HASH", PasswordHasher().hash("old-password"))
    monkeypatch.setenv("RC_PROJECT_PATH", str(tmp_path))
    monkeypatch.delenv("RC_PUBLIC_ORIGIN")
    with TestClient(create_app(lambda: FakeBridge(), database=tmp_path / "conversations.sqlite3")):
        pass
    assert ConfigStore().load().origin == "http://localhost:5173"
    monkeypatch.setenv("RC_PASSWORD_HASH", PasswordHasher().hash("wrong-password"))
    with TestClient(create_app(lambda: FakeBridge(), database=tmp_path / "conversations.sqlite3")) as client:
        assert client.post("/auth/login", json={"password": "old-password"}, headers={"Origin": "http://localhost:5173"}).status_code == 200


def test_remove_then_add_keeps_project_order(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.sqlite3")
    projects = [Project(id, id, tmp_path / id) for id in ("one", "two", "three")]
    store.bootstrap(Configuration(PasswordHasher().hash("password"), "local", "http://127.0.0.1:8765", projects))
    store.remove_project("two")
    store.add_project(Project("four", "four", tmp_path / "four"))
    assert [project.id for project in store.load().projects] == ["one", "three", "four"]
