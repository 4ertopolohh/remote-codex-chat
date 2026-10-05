"""Single-user password verification and server-owned, expiring sessions."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from starlette.websockets import WebSocket

SESSION_AGE = 60 * 60 * 24 * 7
COOKIE_LOCAL = "rc_session"
COOKIE_REMOTE = "__Host-rc_session"


@dataclass(frozen=True)
class AuthSettings:
    password_hash: str
    origin: str
    remote: bool
    database: Path

    @classmethod
    def from_env(cls) -> AuthSettings:
        password_hash = os.environ.get("RC_PASSWORD_HASH", "")
        mode = os.environ.get("RC_AUTH_MODE", "local")
        origin = os.environ.get("RC_PUBLIC_ORIGIN", "" if mode == "remote" else "http://localhost:5173")
        origin = cls.normalize_origin(origin)
        cls.validate(password_hash, mode, origin)
        return cls(password_hash, origin, mode == "remote",
                   Path(os.environ.get("RC_AUTH_DATABASE_PATH", Path(__file__).resolve().parent / "data" / "auth.sqlite3")))

    @staticmethod
    def normalize_origin(origin: str) -> str:
        parsed = urlsplit(origin)
        if (
            not parsed.hostname
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Origin must be an exact scheme and host, without a path")
        try:
            hostname = parsed.hostname.encode("idna").decode("ascii").lower()
            port = parsed.port
        except (UnicodeError, ValueError) as exc:
            raise ValueError("Origin contains an invalid hostname or port") from exc
        if ":" in hostname:
            hostname = f"[{hostname}]"
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        port_suffix = f":{port}" if port is not None and port != default_port else ""
        return f"{parsed.scheme.lower()}://{hostname}{port_suffix}"

    @staticmethod
    def validate(password_hash: str, mode: str, origin: str) -> None:
        if not password_hash.startswith("$argon2id$"):
            raise ValueError("RC_PASSWORD_HASH must contain an Argon2id hash")
        try:
            from argon2 import extract_parameters
            extract_parameters(password_hash)
        except (InvalidHashError, ValueError) as exc:
            raise ValueError("Invalid Argon2id password hash") from exc
        remote = mode == "remote"
        if mode not in {"local", "remote"}:
            raise ValueError("RC_AUTH_MODE must be local or remote")
        parsed = urlsplit(origin)
        if not parsed.scheme or not parsed.netloc or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("RC_PUBLIC_ORIGIN must be one exact origin")
        if remote and parsed.scheme != "https":
            raise ValueError("Remote mode requires an HTTPS RC_PUBLIC_ORIGIN")
        if not remote and parsed.scheme != "http":
            raise ValueError("Local mode requires an HTTP RC_PUBLIC_ORIGIN")
        if not remote and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Local mode requires a loopback RC_PUBLIC_ORIGIN")

    @property
    def cookie_name(self) -> str:
        return COOKIE_REMOTE if self.remote else COOKIE_LOCAL


class AuthService:
    def __init__(self, settings: AuthSettings) -> None:
        self.settings = settings
        self.hasher = PasswordHasher()
        self.failures: dict[str, tuple[int, float]] = {}
        self.sockets: dict[str, set[WebSocket]] = {}

    def initialize(self) -> None:
        self.settings.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sessions (id_hash TEXT PRIMARY KEY, csrf TEXT NOT NULL, expires_at REAL NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.settings.database)

    @staticmethod
    def _digest(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def verify_password(self, password: str) -> bool:
        try:
            return self.hasher.verify(self.settings.password_hash, password)
        except (VerificationError, InvalidHashError):
            return False

    def login(self, password: str, client_ip: str) -> tuple[str, str] | None:
        now = time.time()
        ip_key = f"ip:{client_ip}"
        account_key = "single-user"
        ip_count, ip_until = self.failures.get(ip_key, (0, 0))
        account_count, account_until = self.failures.get(account_key, (0, 0))
        if ip_until > now or account_until > now:
            return None
        if not self.verify_password(password):
            ip_count += 1
            account_count += 1
            self.failures[ip_key] = (ip_count, now + 60 if ip_count >= 5 else 0)
            self.failures[account_key] = (account_count, now + 60 if account_count >= 5 else 0)
            return None
        self.failures.pop(ip_key, None)
        self.failures.pop(account_key, None)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (self._digest(token), csrf, now + SESSION_AGE))
        return token, csrf

    def session(self, token: str | None) -> tuple[str, float] | None:
        if not token:
            return None
        with self._connect() as db:
            row = db.execute("SELECT csrf, expires_at FROM sessions WHERE id_hash = ?", (self._digest(token),)).fetchone()
        if row is None or row[1] <= time.time():
            return None
        return row[0], row[1]

    def logout(self, token: str) -> set[WebSocket]:
        digest = self._digest(token)
        with self._connect() as db:
            db.execute("DELETE FROM sessions WHERE id_hash = ?", (digest,))
        return self.sockets.pop(digest, set())

    def register_socket(self, token: str, socket: WebSocket) -> None:
        self.sockets.setdefault(self._digest(token), set()).add(socket)

    def unregister_socket(self, token: str, socket: WebSocket) -> None:
        sockets = self.sockets.get(self._digest(token))
        if sockets is not None:
            sockets.discard(socket)
            if not sockets:
                self.sockets.pop(self._digest(token), None)
