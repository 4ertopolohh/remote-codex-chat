"""Durable, server-owned application configuration."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from auth import AuthSettings
from projects import Project, ProjectAllowlist


@dataclass(frozen=True)
class Configuration:
    password_hash: str
    mode: str
    origin: str
    projects: list[Project]

    def validate(self) -> None:
        AuthSettings.validate(self.password_hash, self.mode, self.origin)
        ProjectAllowlist(self.projects)


class ConfigStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(os.environ.get(
            "RC_CONFIG_DATABASE_PATH", Path(__file__).resolve().parent / "data" / "config.sqlite3"
        ))

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise ValueError(f"Unsupported configuration schema version: {version}")
            if version == 0:
                existing = db.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'").fetchone()
                if existing is not None:
                    raise ValueError("Configuration database has an unversioned schema; restore a backup")
                db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, position INTEGER NOT NULL UNIQUE)")
                db.execute("PRAGMA user_version = 1")

    def load(self) -> Configuration | None:
        self.initialize()
        with sqlite3.connect(self.path) as db:
            settings = dict(db.execute("SELECT key, value FROM settings"))
            rows = db.execute("SELECT id, name, path FROM projects ORDER BY position").fetchall()
        if not settings and not rows:
            return None
        if set(settings) != {"password_hash", "mode", "origin"}:
            raise ValueError("Configuration database is incomplete; repair it with the local CLI")
        config = Configuration(settings["password_hash"], settings["mode"], settings["origin"],
                               [Project(id, name, Path(path)) for id, name, path in rows])
        config.validate()
        return config

    def bootstrap(self, config: Configuration) -> None:
        config.validate()
        self.initialize()
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM settings LIMIT 1").fetchone() or db.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
                raise ValueError("Configuration already exists; use explicit update commands")
            db.executemany("INSERT INTO settings VALUES (?, ?)",
                           [("password_hash", config.password_hash), ("mode", config.mode), ("origin", config.origin)])
            db.executemany("INSERT INTO projects VALUES (?, ?, ?, ?)",
                           [(p.id, p.name, str(p.path), i) for i, p in enumerate(config.projects)])

    def set_password(self, password_hash: str) -> None:
        config = self.load()
        if config is None:
            raise ValueError("Run init first")
        AuthSettings.validate(password_hash, config.mode, config.origin)
        with sqlite3.connect(self.path) as db:
            db.execute("UPDATE settings SET value = ? WHERE key = 'password_hash'", (password_hash,))

    def add_project(self, project: Project) -> None:
        config = self.load()
        if config is None:
            raise ValueError("Run init first")
        ProjectAllowlist([*config.projects, project])
        with sqlite3.connect(self.path) as db:
            position = db.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM projects").fetchone()[0]
            db.execute("INSERT INTO projects VALUES (?, ?, ?, ?)",
                       (project.id, project.name, str(project.path), position))

    def remove_project(self, project_id: str) -> None:
        config = self.load()
        if config is None or project_id not in {p.id for p in config.projects}:
            raise ValueError("Unknown project")
        if len(config.projects) == 1:
            raise ValueError("At least one project is required")
        with sqlite3.connect(self.path) as db:
            db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
