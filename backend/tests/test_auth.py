from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from conftest import TEST_HASH, TEST_ORIGIN, TEST_PASSWORD
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from test_chat_websocket import FakeBridge

from app import create_app
from auth import AuthService, AuthSettings


def make_client(tmp_path: Path, settings: AuthSettings | None = None) -> TestClient:
    return TestClient(create_app(lambda: FakeBridge(), project=tmp_path, database=tmp_path / "conversations.sqlite3", auth_settings=settings))


def login(client: TestClient, password: str = TEST_PASSWORD):
    return client.post("/auth/login", json={"password": password}, headers={"Origin": TEST_ORIGIN})


def test_http_and_websocket_require_a_session_and_exact_origin(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/ready").status_code == 401
        assert client.get("/auth/session").status_code == 401
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/chat", headers={"Origin": TEST_ORIGIN}) as ws:
            ws.receive_json()
        response = login(client)
        assert response.status_code == 200
        assert client.get("/ready").status_code == 200
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/chat", headers={"Origin": "http://evil.test"}) as ws:
            ws.receive_json()
        with client.websocket_connect("/ws/chat", headers={"Origin": TEST_ORIGIN}) as ws:
            assert ws.receive_json() == {"type": "ready"}


def test_password_hash_cookie_and_generic_throttled_failures(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        assert login(client, "incorrect").json() == {"detail": "Invalid credentials"}
        for _ in range(4):
            assert login(client, "incorrect").status_code == 401
        assert login(client).status_code == 401
        assert login(client, "incorrect").json() == {"detail": "Invalid credentials"}
    with make_client(tmp_path) as client:
        response = login(client)
        assert response.status_code == 200
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie and "max-age=" in cookie
        assert "secure" not in cookie
        assert TEST_PASSWORD not in response.text
        assert TEST_HASH.startswith("$argon2id$")
        with sqlite3.connect(tmp_path / "auth.sqlite3") as db:
            stored = db.execute("SELECT id_hash, csrf FROM sessions").fetchone()
        assert stored is not None
        assert client.cookies["rc_session"] not in stored


def test_login_throttle_covers_rotating_source_ips(tmp_path: Path) -> None:
    auth = AuthService(AuthSettings(TEST_HASH, TEST_ORIGIN, False, tmp_path / "auth.sqlite3"))
    auth.initialize()
    for index in range(5):
        assert auth.login("incorrect", f"192.0.2.{index}") is None
    assert auth.login(TEST_PASSWORD, "198.51.100.1") is None


def test_logout_requires_origin_and_csrf_then_revokes_session(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        csrf = login(client).json()["csrf"]
        assert client.post("/auth/logout", headers={"Origin": TEST_ORIGIN}).status_code == 403
        assert client.post("/auth/logout", headers={"Origin": "http://evil.test", "X-CSRF-Token": csrf}).status_code == 403
        assert client.get("/auth/session").status_code == 200
        assert client.post("/auth/logout", headers={"Origin": TEST_ORIGIN, "X-CSRF-Token": csrf}).status_code == 200
        assert client.get("/auth/session").status_code == 401
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/chat", headers={"Origin": TEST_ORIGIN}) as ws:
            ws.receive_json()


def test_logout_closes_an_active_websocket(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        csrf = login(client).json()["csrf"]
        with client.websocket_connect("/ws/chat", headers={"Origin": TEST_ORIGIN}) as ws:
            assert ws.receive_json() == {"type": "ready"}
            assert client.post("/auth/logout", headers={"Origin": TEST_ORIGIN, "X-CSRF-Token": csrf}).status_code == 200
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()


def test_expired_session_is_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        login(client)
        with sqlite3.connect(tmp_path / "auth.sqlite3") as db:
            db.execute("UPDATE sessions SET expires_at = 0")
        assert client.get("/ready").status_code == 401
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/chat", headers={"Origin": TEST_ORIGIN}) as ws:
            ws.receive_json()


def test_remote_cookie_is_secure_and_configuration_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    remote = AuthSettings(TEST_HASH, "https://chat.example.test", True, tmp_path / "remote.sqlite3")
    with make_client(tmp_path, remote) as client:
        response = client.post("/auth/login", json={"password": TEST_PASSWORD}, headers={"Origin": remote.origin})
        assert response.status_code == 200
        assert "__Host-rc_session=" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
    monkeypatch.delenv("RC_PASSWORD_HASH")
    with pytest.raises(ValueError, match="Argon2id"), make_client(tmp_path):
        pass
    monkeypatch.setenv("RC_PASSWORD_HASH", TEST_HASH)
    monkeypatch.setenv("RC_AUTH_MODE", "remote")
    with pytest.raises(ValueError, match="HTTPS"), make_client(tmp_path):
        pass
