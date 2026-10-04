from __future__ import annotations

import sys
from pathlib import Path

import pytest

from poc.app_server_client import AppServerClient, ServerNotification, ServerRequest

FAKE_SERVER = r"""
import json
import sys


def read():
    line = sys.stdin.readline()
    if not line:
        raise SystemExit(0)
    return json.loads(line)


def send(value):
    sys.stdout.write(json.dumps(value) + "\n")
    sys.stdout.flush()


initialize = read()
assert initialize["method"] == "initialize"
send({
    "id": initialize["id"],
    "result": {
        "userAgent": "fake/1.0",
        "codexHome": "C:/fake",
        "platformFamily": "windows",
        "platformOs": "windows",
    },
})

initialized = read()
assert initialized == {"method": "initialized"}

models = read()
assert models["method"] == "model/list"
send({"method": "thread/status/changed", "params": {"status": {"type": "idle"}}})
send({
    "method": "item/commandExecution/requestApproval",
    "id": "approval-1",
    "params": {"command": "echo hi", "cwd": "C:/tmp"},
})
send({"id": models["id"], "result": {"data": [{"id": "gpt-test"}], "nextCursor": None}})

approval = read()
assert approval == {"id": "approval-1", "result": {"decision": "accept"}}
"""


@pytest.mark.asyncio
async def test_routes_responses_notifications_and_server_requests(tmp_path: Path) -> None:
    fake_server = tmp_path / "fake_server.py"
    fake_server.write_text(FAKE_SERVER, encoding="utf-8")

    client = AppServerClient(
        (sys.executable, "-S", str(fake_server)),
        request_timeout=2.0,
    )

    async with client:
        init = await client.initialize()
        assert init["userAgent"] == "fake/1.0"

        result = await client.request("model/list", {})
        assert result["data"][0]["id"] == "gpt-test"

        first_event = await client.next_event(timeout=1.0)
        assert isinstance(first_event, ServerNotification)
        assert first_event.method == "thread/status/changed"

        second_event = await client.next_event(timeout=1.0)
        assert isinstance(second_event, ServerRequest)
        assert second_event.method == "item/commandExecution/requestApproval"
        assert second_event.request_id == "approval-1"

        await client.respond(second_event.request_id, {"decision": "accept"})
