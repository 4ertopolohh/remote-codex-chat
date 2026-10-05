"""Small SQLite index of application conversations, not Codex transcript data."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class Conversation:
    id: str
    project_id: str
    thread_id: str
    title: str
    created_at: str
    updated_at: str

    def public(self) -> dict[str, str]:
        data = asdict(self)
        del data["thread_id"]
        return data


class ConversationStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > 2:
                raise RuntimeError(
                    f"Unsupported conversation schema version: {version}"
                )
            if version == 0:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS conversations (
                        id TEXT PRIMARY KEY,
                        project_id TEXT NOT NULL,
                        thread_id TEXT NOT NULL UNIQUE,
                        title TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                connection.execute("PRAGMA user_version = 1")
            if version < 2:
                connection.execute("""
                    CREATE TABLE IF NOT EXISTS submissions (
                        request_id TEXT PRIMARY KEY,
                        conversation_id TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                """)
                connection.execute("PRAGMA user_version = 2")

    def claim_submission(self, request_id: str, conversation_id: str) -> bool:
        """Reserve a browser submission before calling the non-idempotent bridge."""
        with self._connect() as connection:
            result = connection.execute(
                "INSERT OR IGNORE INTO submissions VALUES (?, ?, ?)",
                (request_id, conversation_id, datetime.now(UTC).isoformat()),
            )
            return result.rowcount == 1

    def create(self, project_id: str, thread_id: str) -> Conversation:
        now = datetime.now(UTC).isoformat()
        conversation = Conversation(
            str(uuid4()), project_id, thread_id, "New conversation", now, now
        )
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO conversations VALUES (?, ?, ?, ?, ?, ?)",
                tuple(asdict(conversation).values()),
            )
        return conversation

    def get(self, conversation_id: str, project_id: str) -> Conversation | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM conversations WHERE id = ? AND project_id = ?",
                (conversation_id, project_id),
            ).fetchone()
        return Conversation(**dict(row)) if row else None

    def list(self, project_id: str) -> list[Conversation]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC, id DESC",
                (project_id,),
            ).fetchall()
        return [Conversation(**dict(row)) for row in rows]

    def record_prompt(self, conversation: Conversation, prompt: str) -> Conversation:
        title = conversation.title
        if conversation.updated_at == conversation.created_at:
            title = " ".join(prompt.split())[:80] or title
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
                (title, updated_at, conversation.id),
            )
        return Conversation(
            conversation.id,
            conversation.project_id,
            conversation.thread_id,
            title,
            conversation.created_at,
            updated_at,
        )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path)) as connection:
            connection.row_factory = sqlite3.Row
            with connection:
                yield connection
