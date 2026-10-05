from __future__ import annotations

import sys
from pathlib import Path

from conftest import AuthenticatedTestClient as TestClient

from app import create_app
from codex_bridge import CodexBridge


def test_fastapi_lifecycle_and_readiness(tmp_path: Path) -> None:
    server = tmp_path / "fake_server.py"
    server.write_text(
        "import json, sys\n"
        "request = json.loads(sys.stdin.readline())\n"
        "print(json.dumps({'id': request['id'], 'result': {}}), flush=True)\n"
        "assert json.loads(sys.stdin.readline()) == {'method': 'initialized'}\n"
        "sys.stdin.readline()\n"
        "open(sys.argv[1], 'w').write('closed')\n",
        encoding="utf-8",
    )
    marker = tmp_path / "closed.txt"
    app = create_app(
        lambda: CodexBridge(command=(sys.executable, "-S", str(server), str(marker)))
    )
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/ready").json() == {"status": "ready"}
    assert marker.read_text() == "closed"
