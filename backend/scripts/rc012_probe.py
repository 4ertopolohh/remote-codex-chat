"""Probe the authenticated application path through a public HTTPS tunnel.

Set RC012_ORIGIN and RC012_PASSWORD in the process environment. The password is
never printed or stored by this script. This PC-side probe cannot replace a
physical-phone test on mobile data.
"""

from __future__ import annotations

import asyncio
import json
import os
from urllib.parse import urlsplit

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus


async def expect_event(socket, event_type: str, timeout: float = 45) -> dict:
    while True:
        event = json.loads(await asyncio.wait_for(socket.recv(), timeout))
        if event.get("type") == "error":
            raise RuntimeError(f"Application error: {event.get('code')}")
        if event.get("type") == event_type:
            return event


async def collect_turn(socket, expected_status: str) -> tuple[str, int]:
    deltas: list[str] = []
    while True:
        event = json.loads(await asyncio.wait_for(socket.recv(), 90))
        if event.get("type") == "assistant_delta":
            deltas.append(event["text"])
        elif event.get("type") == "error":
            raise RuntimeError(f"Application error: {event.get('code')}")
        elif event.get("type") == "turn_completed":
            assert event["status"] == expected_status, event["status"]
            return "".join(deltas), len(deltas)


async def main() -> None:
    origin = os.environ["RC012_ORIGIN"].rstrip("/")
    password = os.environ["RC012_PASSWORD"]
    parsed = urlsplit(origin)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path:
        raise ValueError("RC012_ORIGIN must be an exact HTTPS origin")
    ws_url = os.environ.get("RC012_WS_URL", f"wss://{parsed.netloc}/ws/chat")

    with httpx.Client(timeout=20, follow_redirects=False) as client:
        page = client.get(origin)
        assert page.status_code == 200 and "text/html" in page.headers["content-type"]
        print("HTTPS page: 200")

        anonymous = client.get(f"{origin}/auth/session")
        assert anonymous.status_code == 401
        print("Anonymous session: 401")

        login = client.post(
            f"{origin}/auth/login",
            headers={"Origin": origin},
            json={"password": password},
        )
        assert login.status_code == 200, f"Login failed: {login.status_code}"
        cookie = login.headers["set-cookie"]
        assert "__Host-rc_session=" in cookie
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
        print("Login and remote cookie: 200, Secure/HttpOnly/SameSite=Strict")
        session = client.get(f"{origin}/auth/session")
        assert session.status_code == 200
        ready = client.get(f"{origin}/ready")
        assert ready.status_code == 200, f"Bridge not ready: {ready.status_code}"
        print("Authenticated session and Codex readiness: 200")

        try:
            async with connect(ws_url, origin=origin, open_timeout=15):
                raise AssertionError("Anonymous WebSocket was accepted")
        except InvalidStatus as exc:
            assert exc.response.status_code in {401, 403}, exc.response.status_code
            print(f"Anonymous WebSocket: rejected ({exc.response.status_code})")

        session_cookie = client.cookies.get("__Host-rc_session")
        assert session_cookie
        try:
            async with connect(
                ws_url,
                origin="https://invalid.example",
                additional_headers={"Cookie": f"__Host-rc_session={session_cookie}"},
                open_timeout=15,
            ):
                raise AssertionError("WebSocket with a wrong Origin was accepted")
        except InvalidStatus as exc:
            assert exc.response.status_code in {401, 403}, exc.response.status_code
            print(f"Wrong-Origin WebSocket: rejected ({exc.response.status_code})")
        async with connect(
            ws_url,
            origin=origin,
            additional_headers={"Cookie": f"__Host-rc_session={session_cookie}"},
            open_timeout=15,
            ping_interval=20,
        ) as socket:
            await expect_event(socket, "ready")
            print("Authenticated WebSocket: 101, ready")
            await socket.send(json.dumps({"type": "list_projects"}))
            projects = await expect_event(socket, "project_list")
            assert projects["projects"]
            print("Bidirectional WebSocket: project_list")
            await socket.send(json.dumps({"type": "new_conversation"}))
            await expect_event(socket, "conversation_selected")
            await socket.send(json.dumps({"type": "submit_prompt", "text": "Reply with exactly: RC-012 tunnel probe OK"}))
            await expect_event(socket, "turn_started", timeout=15)
            print("Real Codex turn: started")
            reply, count = await collect_turn(socket, "completed")
            assert "RC-012 tunnel probe OK" in reply
            print(f"Real Codex streaming: completed ({count} deltas)")

            await socket.send(json.dumps({"type": "submit_prompt", "text": "Write a numbered list from 1 to 80. Each line should contain only its number and the word ready."}))
            await expect_event(socket, "turn_started", timeout=15)
            long_reply, long_count = await collect_turn(socket, "completed")
            assert len(long_reply) >= 300
            print(f"Long Codex streaming: completed ({long_count} deltas)")

            await socket.send(json.dumps({"type": "submit_prompt", "text": "Write a very long story with at least 100 chapters. Start immediately."}))
            await expect_event(socket, "turn_started")
            await socket.send(json.dumps({"type": "stop_turn"}))
            await collect_turn(socket, "interrupted")
            print("Stop: turn interrupted")

        async with connect(
            ws_url,
            origin=origin,
            additional_headers={"Cookie": f"__Host-rc_session={session_cookie}"},
            open_timeout=15,
        ) as socket:
            await expect_event(socket, "ready")
            print("WebSocket reconnect: ready")
            idle_seconds = int(os.environ.get("RC012_IDLE_SECONDS", "0"))
            if idle_seconds:
                await asyncio.sleep(idle_seconds)
                await socket.send(json.dumps({"type": "list_projects"}))
                await expect_event(socket, "project_list", timeout=15)
                print(f"WebSocket idle: responsive after {idle_seconds}s")


if __name__ == "__main__":
    asyncio.run(main())
