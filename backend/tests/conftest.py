from __future__ import annotations

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient as BaseTestClient

TEST_PASSWORD = "test-password"
TEST_ORIGIN = "http://testserver"
TEST_HASH = PasswordHasher().hash(TEST_PASSWORD)


@pytest.fixture(autouse=True)
def auth_environment(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("RC_PASSWORD_HASH", TEST_HASH)
    monkeypatch.setenv("RC_PUBLIC_ORIGIN", TEST_ORIGIN)
    monkeypatch.setenv("RC_AUTH_DATABASE_PATH", str(tmp_path / "auth.sqlite3"))
    monkeypatch.setenv("RC_AUTH_MODE", "local")


class AuthenticatedTestClient(BaseTestClient):
    """Legacy chat tests exercise the protocol after an explicit real login."""

    def __enter__(self):
        client = super().__enter__()
        response = client.post(
            "/auth/login", json={"password": TEST_PASSWORD}, headers={"Origin": TEST_ORIGIN}
        )
        assert response.status_code == 200
        return client

    def websocket_connect(self, url, subprotocols=None, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["Origin"] = TEST_ORIGIN
        return super().websocket_connect(url, subprotocols=subprotocols, headers=headers, **kwargs)
