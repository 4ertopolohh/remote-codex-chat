"""Exercise the real local FastAPI-to-Codex path without printing credentials."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path
from subprocess import DEVNULL

import httpx
from argon2 import PasswordHasher
from websockets.asyncio.client import connect

ORIGIN = "http://127.0.0.1:8766"


async def event_of(socket, kind: str, timeout: float = 90) -> dict:
    while True:
        event = json.loads(await asyncio.wait_for(socket.recv(), timeout))
        if event.get("type") == "error":
            raise RuntimeError(f"Application error: {event.get('code')}")
        if event.get("type") == kind:
            return event


async def turn(socket, prompt: str, *, stop: bool = False, model: dict | None = None) -> int:
    message = {"type": "submit_prompt", "text": prompt}
    if model is not None:
        message["model_id"] = model["id"]
        message["reasoning_effort"] = model["default_reasoning_effort"]
    await socket.send(json.dumps(message))
    await event_of(socket, "turn_started")
    deltas = 0
    if stop:
        while not deltas:
            event = json.loads(await asyncio.wait_for(socket.recv(), 120))
            if event.get("type") == "error":
                raise RuntimeError(f"Application error: {event.get('code')}")
            if event.get("type") == "turn_completed":
                raise RuntimeError("Turn completed before Stop could be exercised")
            if event.get("type") == "assistant_delta":
                deltas += 1
        await socket.send(json.dumps({"type": "stop_turn"}))
    while True:
        event = json.loads(await asyncio.wait_for(socket.recv(), 120))
        if event.get("type") == "error":
            raise RuntimeError(f"Application error: {event.get('code')}")
        if event.get("type") == "assistant_delta":
            deltas += 1
        if event.get("type") == "turn_completed":
            expected = "interrupted" if stop else "completed"
            assert event["status"] == expected, event
            return deltas


async def main() -> None:
    password = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory(prefix="rc014-local-") as directory:
        env = os.environ.copy()
        env.update({
            "RC_PASSWORD_HASH": PasswordHasher().hash(password),
            "RC_AUTH_MODE": "local",
            "RC_PUBLIC_ORIGIN": ORIGIN,
            "RC_AUTH_DATABASE_PATH": str(Path(directory) / "auth.sqlite3"),
            "RC_DATABASE_PATH": str(Path(directory) / "conversations.sqlite3"),
        })
        server = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", "8766",
            env=env,
            stdout=DEVNULL,
            stderr=DEVNULL,
        )
        try:
            async with httpx.AsyncClient(base_url=ORIGIN, timeout=10) as client:
                for _ in range(100):
                    if server.returncode is not None:
                        raise RuntimeError(f"Backend exited with code {server.returncode}")
                    try:
                        if (await client.get("/health")).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    await asyncio.sleep(0.2)
                else:
                    raise RuntimeError("Backend did not become healthy")
                assert (await client.get("/")).status_code == 200
                assert (await client.get("/auth/session")).status_code == 401
                login = await client.post("/auth/login", headers={"Origin": ORIGIN}, json={"password": password})
                assert login.status_code == 200, login.status_code
                assert (await client.get("/ready")).status_code == 200
                cookie = client.cookies.get("rc_session")
                assert cookie
                headers = {"Cookie": f"rc_session={cookie}"}
                async with connect("ws://127.0.0.1:8766/ws/chat", origin=ORIGIN, additional_headers=headers) as socket:
                    await event_of(socket, "ready")
                    await socket.send(json.dumps({"type": "list_projects"}))
                    projects = await event_of(socket, "project_list")
                    assert projects["projects"]
                    await socket.send(json.dumps({"type": "select_project", "id": "unknown-project"}))
                    rejected = json.loads(await asyncio.wait_for(socket.recv(), 10))
                    assert rejected.get("type") == "error"
                    await socket.send(json.dumps({"type": "list_capabilities"}))
                    capabilities = await event_of(socket, "capabilities")
                    assert capabilities["models"]
                    model = next((item for item in capabilities["models"] if item["is_default"]), capabilities["models"][0])
                    await socket.send(json.dumps({"type": "new_conversation"}))
                    selected = await event_of(socket, "conversation_selected")
                    conversation_id = selected["conversation"]["id"]
                    deltas = await turn(socket, "Reply with exactly: RC014_LOCAL_OK", model=model)
                    assert deltas > 0
                    await socket.send(json.dumps({"type": "read_usage"}))
                    usage = await event_of(socket, "usage")
                    assert usage
                    await turn(socket, "Write a very long story with 100 chapters. Start immediately.", stop=True)
                async with connect("ws://127.0.0.1:8766/ws/chat", origin=ORIGIN, additional_headers=headers) as socket:
                    await event_of(socket, "ready")
                    await socket.send(json.dumps({"type": "select_conversation", "id": conversation_id}))
                    await event_of(socket, "conversation_selected")
                    resumed_deltas = await turn(socket, "Reply with exactly: RC014_RESUME_OK")
                    assert resumed_deltas > 0
                session = await client.get("/auth/session")
                assert session.status_code == 200
                logout = await client.post("/auth/logout", headers={"Origin": ORIGIN, "X-CSRF-Token": session.json()["csrf"]})
                assert logout.status_code == 200
                assert (await client.get("/auth/session")).status_code == 401
                print("PASS: build, login, ready, project rejection, model/effort, new turn/stream, usage, Stop, reconnect/resume, logout")
        finally:
            server.terminate()
            try:
                await asyncio.wait_for(server.wait(), 10)
            except TimeoutError:
                server.kill()
                await asyncio.wait_for(server.wait(), 5)


if __name__ == "__main__":
    asyncio.run(main())
