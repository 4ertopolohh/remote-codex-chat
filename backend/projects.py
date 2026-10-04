"""Server-owned project allowlist and safe public project metadata."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

_ID = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


class ProjectUnavailable(Exception):
    """A configured project cannot currently be used."""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: Path

    def public(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}


class ProjectAllowlist:
    def __init__(self, projects: list[Project]) -> None:
        if not projects:
            raise ValueError("At least one project is required")
        seen_ids: set[str] = set()
        seen_paths: set[Path] = set()
        for project in projects:
            if not _ID.fullmatch(project.id) or project.id in seen_ids:
                raise ValueError("Project IDs must be unique lowercase slugs")
            if not project.name.strip() or "/" in project.name or "\\" in project.name:
                raise ValueError("Project names must be display labels")
            if not project.path.is_absolute():
                raise ValueError("Project paths must be absolute")
            path = project.path.resolve()
            if path in seen_paths:
                raise ValueError("Project paths must be unique")
            seen_ids.add(project.id)
            seen_paths.add(path)
        self._projects = {project.id: project for project in projects}
        self.default_id = projects[0].id

    @classmethod
    def from_json(cls, value: str) -> ProjectAllowlist:
        try:
            raw = json.loads(value)
            if not isinstance(raw, list):
                raise TypeError("RC_PROJECTS must be a JSON array")
            projects = []
            for entry in raw:
                if not isinstance(entry, dict) or set(entry) != {"id", "name", "path"}:
                    raise ValueError("Each project needs id, name, and path")
                if not all(isinstance(entry[key], str) for key in ("id", "name", "path")):
                    raise ValueError("Project fields must be strings")
                projects.append(Project(entry["id"], entry["name"], Path(entry["path"])))
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError("Invalid RC_PROJECTS JSON") from exc
        return cls(projects)

    def public(self) -> list[dict[str, str]]:
        return [project.public() for project in self._projects.values()]

    def contains(self, project_id: str) -> bool:
        return project_id in self._projects

    def resolve(self, project_id: str) -> Path:
        project = self._projects.get(project_id)
        if project is None:
            raise KeyError(project_id)
        try:
            path = project.path.resolve(strict=True)
            if not path.is_dir():
                raise ProjectUnavailable
            with os.scandir(path):
                pass
        except (OSError, RuntimeError, ProjectUnavailable) as exc:
            raise ProjectUnavailable from exc
        return path
