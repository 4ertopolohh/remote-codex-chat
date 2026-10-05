"""Local configuration management. Run from backend with `python scripts/configure.py`."""

from __future__ import annotations

import argparse
import sys
from getpass import getpass
from pathlib import Path

from argon2 import PasswordHasher
from argon2.low_level import Type

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config_store import ConfigStore, Configuration
from projects import Project


def password_hash() -> str:
    password = getpass("Password: ")
    confirmation = getpass("Confirm password: ")
    if not password or password != confirmation:
        raise ValueError("Passwords are empty or do not match")
    return PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, type=Type.ID).hash(password)


def project_prompt() -> Project:
    return Project(input("Project ID: ").strip(), input("Display name: ").strip(),
                   Path(input("Absolute project path: ").strip()))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["init", "list", "set-password", "set-origin", "add-project", "remove-project"])
    parser.add_argument("value", nargs="?", help="Origin for set-origin or project ID for remove-project")
    args = parser.parse_args()
    store = ConfigStore()
    if args.command == "init":
        if store.load() is not None:
            raise ValueError("Configuration already exists; use explicit update commands")
        mode = input("Auth mode [local]: ").strip() or "local"
        default = "http://127.0.0.1:8765" if mode == "local" else ""
        origin = input(f"Public origin [{default}]: ").strip() or default
        projects = [project_prompt()]
        while input("Add another project? [y/N]: ").strip().lower() == "y":
            projects.append(project_prompt())
        store.bootstrap(Configuration(password_hash(), mode, origin, projects))
        print("Configuration saved. Restart the backend to load it.")
    elif args.command == "list":
        config = store.load()
        if config is None:
            raise ValueError("Run init first")
        print(f"Mode: {config.mode}; origin: {config.origin}")
        for project in config.projects:
            print(f"{project.id}: {project.name} -> {project.path}")
    elif args.command == "set-password":
        store.set_password(password_hash())
        print("Password updated. Restart the backend to load it.")
    elif args.command == "set-origin":
        if not args.value:
            parser.error("set-origin requires an exact origin, for example https://chat.example.com")
        mode = store.set_origin(args.value)
        print(f"Origin saved in {mode} mode. Restart the backend to load it.")
    elif args.command == "add-project":
        store.add_project(project_prompt())
        print("Project added. Restart the backend to load it.")
    else:
        if not args.value:
            parser.error("remove-project requires a project ID")
        store.remove_project(args.value)
        print("Project removed. Restart the backend to load it.")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
