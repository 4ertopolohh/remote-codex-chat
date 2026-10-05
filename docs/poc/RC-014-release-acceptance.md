# RC-014 release acceptance

Checked on 2026-10-05 on the target Windows PC. Versions: uv 0.12.23, Python 3.12.15 (uv-managed), Node.js 24.13.1, npm 11.8.0, codex-cli 0.160.0. No physical phone or mobile-data session was available in this run.

## Reproducibility and checks

The clean-equivalent checkout was a fresh detached `git worktree` in a temporary directory with no `backend/.venv`, `frontend/node_modules`, or `frontend/dist`. From it:

| Command | Result |
| --- | --- |
| `cd backend; uv sync --locked --dev` | PASS: created Python 3.12.15 environment and installed 58 locked packages. |
| `cd backend; uv run --no-sync ruff check .` | PASS. |
| `cd backend; uv run --no-sync pytest -q` | Initially FAIL: one remote cookie test depended on a pre-existing `frontend/dist/index.html` while frontend build ran in parallel. A test-owned build fixture was added. Final clean rerun recorded below. |
| `cd frontend; npm ci` | PASS: installed 232 packages from lockfile, npm reported 0 vulnerabilities at check time. |
| `cd frontend; npm run lint` | PASS. |
| `cd frontend; npm test` | PASS: 33 tests in 8 files. |
| `cd frontend; npm run build` | PASS: TypeScript and Vite production build. |

The targeted regression command `cd backend; uv run --no-sync pytest tests/test_auth.py::test_remote_cookie_is_secure_and_configuration_fails_closed -q` passed (1 test). The full working-checkout backend suite passed (60 tests) after the fixture change, with three Windows/Starlette warnings about deprecated TestClient and subprocess transports. These are warnings, not failing checks.

## Real local Codex evidence

`codex login status` reported `Logged in using ChatGPT`. `cd backend; uv run --no-sync python -m poc.rc006_real_approval_check` completed a real command approval for `echo RC006_OK` in a disposable Git repository; the temporary repository remained clean. The new `cd backend; uv run --no-sync python scripts/rc014_local_probe.py` passed with a real local app-server: built page, anonymous rejection, login, authenticated readiness, unknown-project rejection, dynamic model and reasoning choice, new conversation, text streaming, usage response, Stop after streaming began, WebSocket reconnect, persistent conversation selection, follow-up prompt, and logout. It uses temporary databases and prints no credentials or account values.

Two early Stop attempts sent immediately after `turn_started` returned `stop_failed` from the current Codex runtime. A Stop after the first assistant delta returned `interrupted`. The UI can show Stop before a delta, so the early race is a known unresolved behavior; its impact and fix need review before claiming unconditional Stop acceptance.

## Remote and mobile acceptance

The earlier [RC-012 PC-side CloudPub probe](RC-012-remote-access.md) passed HTTPS, auth, WSS, real streaming, Stop and reconnect through the tunnel. It did **not** prove a physical phone on mobile data or the normal Happ VPN path. This RC-014 run did not repeat the public tunnel or inspect a phone. The complete phone → HTTPS tunnel → login → project → conversation → model/effort → prompt/stream → status → Stop → resume → approval → usage → reconnect sequence is **NOT VERIFIED**. Browser-level mobile visual acceptance is also **NOT VERIFIED** in this run. See RC-012's phone checklist before a release verdict.

## Audit and guardrails

Removed tracked `repomix-output.xml`, extended ignore rules for backend runtime data and SQLite sidecars, and removed private absolute Windows paths from historical docs. A tracked-file scan found no private-key header, GitHub/OpenAI token pattern, or CloudPub token assignment. `.env.example` contains placeholder values and documents all `RC_*` variables read by application code. `.github/workflows/checks.yml` runs locked backend and frontend checks on Windows for pushes and PRs; the workflow itself has not executed on GitHub until this branch is pushed.
