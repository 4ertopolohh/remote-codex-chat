# Remote Codex Chat

A single-user phone-friendly browser interface to **Codex running on your Windows PC**. The browser talks to FastAPI over HTTP/WebSocket; FastAPI owns authentication, the project allowlist, a SQLite conversation index, and a `CodexBridge` that starts the local `codex app-server` over stdio. For remote access, an HTTPS tunnel forwards only to FastAPI on loopback. The app-server is never published and the browser never receives Codex credentials or arbitrary filesystem access.

This is a personal experimental application, not a hosted multi-user service. The [architecture](docs/architecture.md) and [accepted PoC notes](docs/poc/) explain the protocol and recovery decisions.

## Prerequisites

- Windows with PowerShell, Git, [uv](https://docs.astral.sh/uv/getting-started/installation/), Node.js 24 and npm. `uv` installs the locked Python 3.12 environment (`requires-python >=3.12`).
- [Codex CLI](https://developers.openai.com/codex/cli) on `PATH`, signed in **as the same Windows user that starts FastAPI**. Confirm `codex --version` and `codex login status`. The browser needs no OpenAI key. Test against `codex-cli 0.160.0` or revalidate protocol-sensitive behavior after changing it.
- For access outside the PC: a CloudPub account/client and a registered HTTPS publication to `http://127.0.0.1:8765`. See the [remote-access evidence and phone checklist](docs/poc/RC-012-remote-access.md). Its physical-phone test is still pending.

Clone the repository and open PowerShell in its root. Commands below assume two or three separate PowerShell windows. `uv run` uses `backend/.venv`; `npm ci` replaces `frontend/node_modules` from the lockfile. The `.env.example` file is a **reference only**; the application does not load it automatically.

## Local development

Install dependencies from both committed lockfiles:

```powershell
cd backend
uv sync --locked --dev
uv run python scripts/hash_password.py
```

The password script asks twice and prints an Argon2id **hash**, not the password. Keep both private. In this backend shell, set the printed hash in the process environment (PowerShell history may retain a pasted hash; a private process manager is preferable for routine use):

```powershell
$env:RC_PASSWORD_HASH = '<private Argon2id hash>'
$env:RC_AUTH_MODE = 'local'
$env:RC_PUBLIC_ORIGIN = 'http://localhost:5173'
uv run uvicorn app:app --host 127.0.0.1 --port 8000
```

In a second shell:

```powershell
cd frontend
npm ci
npm run dev -- --host localhost --port 5173 --strictPort
```

Open `http://localhost:5173`, log in with the original password, choose a project, and start a conversation. Vite proxies `/auth` and `/ws` to the loopback backend. Origin matching is exact: if you change the host or port, update `RC_PUBLIC_ORIGIN` before starting FastAPI. `127.0.0.1` and `localhost` are different origins.

## Configuration and project allowlist

Set variables in the **backend process environment**. Defaults and safe placeholders are in [.env.example](.env.example). A private `.env` may be loaded externally by a process manager; `uvicorn` does not read it by default.

| Variable | Purpose / default |
| --- | --- |
| `RC_PASSWORD_HASH` | Required Argon2id hash from `scripts/hash_password.py`; never the plaintext password. |
| `RC_AUTH_MODE` | `local` (default) or `remote`. Remote requires HTTPS and a built frontend. |
| `RC_PUBLIC_ORIGIN` | Exact browser origin, with no path or trailing slash. Defaults to `http://localhost:5173` in local mode; required in remote mode. |
| `RC_PROJECTS` | JSON array of allowed `{id,name,path}` entries; absolute existing directories only. First is default. Overrides `RC_PROJECT_PATH`. |
| `RC_PROJECT_PATH` | Legacy one-project fallback; default is this repository's root. |
| `RC_DATABASE_PATH` | Conversation index; default `backend/data/conversations.sqlite3`. |
| `RC_AUTH_DATABASE_PATH` | Session database; default `backend/data/auth.sqlite3`. |
| `RC_FRONTEND_DIST` | Built frontend directory; default `frontend/dist`. |
| `RC_EXPERIMENTAL_FEATURES` | `1` opts into experimental Codex methods; disabled by default. |

For multiple projects, set `RC_PROJECTS` before starting the backend. In PowerShell, generating JSON from objects avoids backslash escaping errors:

```powershell
$projects = @(
  @{ id = 'app-one'; name = 'App One'; path = 'C:\Projects\app-one' },
  @{ id = 'app-two'; name = 'App Two'; path = 'D:\Projects\app-two' }
)
$env:RC_PROJECTS = ConvertTo-Json -InputObject $projects -Compress -Depth 3
```

Replace those example paths with existing local directories. Browser requests contain only IDs; unknown project IDs and unavailable directories are rejected by the server. Do not grant access to a broad directory if Codex should work only in one project.

## Production build and selected tunnel

Build and start in this order: configure projects and password, build frontend, start backend, confirm loopback health, then start **one** CloudPub publication. From `frontend/`, run `npm ci` and `npm run build`. From `backend/`, run `uv sync --locked --dev` (or `uv sync --locked --no-dev` for runtime only), then:

```powershell
$env:RC_PASSWORD_HASH = '<private Argon2id hash>'
$env:RC_AUTH_MODE = 'remote'
$env:RC_PUBLIC_ORIGIN = 'https://<assigned-host>.cloudpub.ru'
uv run uvicorn app:app --host 127.0.0.1 --port 8765
```

Get the exact assigned origin and publication GUID from the CloudPub client while the publication is stopped. Register the service target as **`http://127.0.0.1:8765`**. In another shell run `clo start <publication-GUID>` and leave it open. Avoid `clo run` (it starts all services) and concurrent `clo` commands on the same configuration while the publication is active; the [RC-012 test](docs/poc/RC-012-remote-access.md) observed client interference. Open the assigned HTTPS URL on the phone. Keep the backend to one worker because the bridge and login throttle are process-local. If your CloudPub version changes, consult its current CLI help/docs for the exact registration command.

`GET /health` is public and reports process liveness; authenticated `GET /ready` reports Codex bridge readiness. Serve the frontend and API on the same HTTPS origin. Never bind FastAPI or `codex app-server` to a public interface. Keep the CloudPub token in its own client configuration and the two SQLite files in private persistent storage. Sessions use an HttpOnly host-only cookie; remote cookies require HTTPS. Logout revokes the session and closes its chat socket. Do not copy password hashes, cookies, tunnel credentials, or account data into the browser bundle or Git.

## Checks and troubleshooting

Run the same checks as [GitHub Actions](.github/workflows/checks.yml):

```powershell
cd backend
uv sync --locked --dev
uv run --no-sync ruff check .
uv run --no-sync pytest -q

cd ..\frontend
npm ci
npm run lint
npm test
npm run build
```

With a built frontend and a signed-in local Codex CLI, run `cd backend; uv run --no-sync python scripts/rc014_local_probe.py` for a real loopback smoke test. It uses a random temporary password, project, and databases, starts FastAPI on `127.0.0.1:8766`, and stops it afterward. Port 8766 must be free. This checks the application path, but does not replace the physical-phone tunnel test.

If backend startup fails, confirm `RC_PASSWORD_HASH` starts with `$argon2id$`, `codex` is on `PATH` and signed in for this Windows user, the project directories exist, and `frontend/dist/index.html` exists in remote mode. If login or WebSocket fails, compare the browser's exact scheme/host/port with `RC_PUBLIC_ORIGIN`, and use HTTPS in remote mode. A public `/health` success does not mean `/ready` or login works. If the tunnel returns 503 but loopback `/health` works, inspect the foreground CloudPub client and restart only the registered publication. If a turn's outcome is uncertain after disconnection, review the persisted conversation before resubmitting; prompts are not replayed automatically. See [recovery behavior](docs/poc/RC-013-resilience.md).

The UI supports one browser connection and one active turn at a time. Long conversation history has no native pagination. Model and reasoning options come from the current Codex runtime; optional experimental collaboration and user-input methods may disappear or fail. Usage data can be unavailable or delayed. Approvals appear only when Codex actually requests one; file approvals show limited scope and require explicit acknowledgement. The physical-phone, normal VPN, and 10-minute tunnel acceptance matrix remains [unverified](docs/poc/RC-012-remote-access.md).

After upgrading Codex, record `codex --version`, rerun the backend and frontend checks, then validate live `model/list`, thread creation/resume/read, prompt streaming, Stop, approvals (if triggered), usage, and reconnect through the real application. Compare any changed request/notification shapes with the [protocol notes](docs/poc/RC-002-protocol-verification.md) and [capability research](docs/poc/RC-005-capabilities-research.md). A passing fake app-server test does not prove compatibility with a new Codex binary.
