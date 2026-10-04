# RC-001 — Codex app-server PoC

This Phase 0 PoC validates the critical local integration before any React UI or FastAPI WebSocket bridge is built.

## What this PoC covers

- starts `codex app-server` as a local child process over stdio;
- performs the required `initialize` → `initialized` handshake;
- calls `model/list`;
- starts a persistent thread with a local `cwd`;
- starts a turn and prints `item/agentMessage/delta` streaming notifications;
- surfaces app-server notifications, including thread status changes;
- handles command/file approval requests with explicit `prompt`, `accept`, or `decline` behavior;
- supports `turn/interrupt`;
- resumes a persisted thread by `threadId` after starting a new app-server process;
- calls `account/rateLimits/read`.

It intentionally does **not** add FastAPI routes, WebSocket transport, authentication, SQLite, CloudPub, or frontend code.

## Prerequisites

Run these checks in PowerShell:

```powershell
codex --version
codex app-server --help
```

Codex must already be signed in on this Windows account. The PoC does not accept or store an OpenAI API key.

## 1. Run automated transport tests

From the repository root:

```powershell
Set-Location "$HOME\Documents\WebProjects\remote-codex-chat\backend"
uv sync
uv run pytest
uv run ruff check .
```

The automated test uses a fake local subprocess. It verifies JSON message routing without consuming Codex usage.

## 2. Verify `model/list`

```powershell
Set-Location "$HOME\Documents\WebProjects\remote-codex-chat\backend"
uv run python -m poc.codex_app_server_poc models
```

Expected result: initialization succeeds and a model catalog is printed.

## 3. Create a disposable Git repository

Do not use `remote-codex-chat` itself for the file-modification PoC.

```powershell
$PocRepo = Join-Path $env:TEMP "remote-codex-chat-poc"
New-Item -ItemType Directory -Path $PocRepo -Force | Out-Null
git -C $PocRepo init -b main
"seed" | Set-Content -Path (Join-Path $PocRepo "seed.txt")
git -C $PocRepo add .
git -C $PocRepo commit -m "chore: seed codex poc workspace"
```

## 4. Start a thread and verify streaming/status events

```powershell
Set-Location "$HOME\Documents\WebProjects\remote-codex-chat\backend"

uv run python -m poc.codex_app_server_poc chat `
    --project $PocRepo `
    --prompt "Read seed.txt and reply with exactly: REMOTE_CODEX_CHAT_POC_OK"
```

Keep the printed `THREAD_ID`. The command prints raw event envelopes as well as assistant deltas.

GO criteria:

- `thread/start` returns a thread id;
- a turn starts;
- at least one agent-message event is observed;
- `turn/completed` reports `completed`.

## 5. Verify file change + approval handling

Use the disposable repository only:

```powershell
uv run python -m poc.codex_app_server_poc chat `
    --project $PocRepo `
    --approval-policy untrusted `
    --approval-mode prompt `
    --prompt "Create proof.txt containing exactly RC001_OK. Ask for approval when required."
```

If app-server emits `item/commandExecution/requestApproval` or `item/fileChange/requestApproval`, the PoC asks for an explicit local decision and returns it through the same JSON-RPC connection.

After accepting, verify:

```powershell
Get-Content (Join-Path $PocRepo "proof.txt")
git -C $PocRepo status --short
```

Expected file content: `RC001_OK`.

If the current Codex policy completes this write without an approval request, record that fact; do not treat it as proof that the approval protocol is unavailable. The next test should use an action that the active policy actually requires approval for.

## 6. Verify resume after app-server restart

Run a new PoC process using the `THREAD_ID` from step 4:

```powershell
$ThreadId = "<paste THREAD_ID>"

uv run python -m poc.codex_app_server_poc resume `
    --thread-id $ThreadId `
    --prompt "What exact text did seed.txt contain when we first talked?"
```

GO criterion: the resumed thread has prior conversation context.

## 7. Verify interrupt

Use a task that will remain active long enough to interrupt:

```powershell
uv run python -m poc.codex_app_server_poc chat `
    --project $PocRepo `
    --interrupt-after 2 `
    --prompt "Inspect this repository carefully and describe it in detail."
```

GO criterion: `turn/interrupt` succeeds and the final turn status is `interrupted`. The command exits with code `2`, which is intentional for a non-completed turn.

## 8. Verify account rate limits

```powershell
uv run python -m poc.codex_app_server_poc limits
```

GO criterion: `account/rateLimits/read` returns a structured response or a clearly attributable account/auth capability error.

## RC-001 GO / NO-GO

**GO** when the real local Codex installation demonstrates:

1. initialize/initialized;
2. model list;
3. thread start;
4. turn start;
5. streaming;
6. observable status events;
7. real local file modification in the disposable repo;
8. approval request/response when policy requires it;
9. interrupt;
10. resume across a new app-server process;
11. rate-limit read.

**NO-GO** if the installed Codex version or current ChatGPT authentication cannot provide the core thread/turn/streaming flow. Do not start the full frontend before resolving that failure.

Record the tested `codex --version`, the commands used, and any protocol differences discovered from the installed version.
