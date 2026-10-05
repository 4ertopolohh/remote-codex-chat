# RC-012: CloudPub remote-access PoC

Checked on 2026-10-05 on the target Windows PC. This is **PC-side evidence only**. The required physical-phone/mobile-data check is pending, so CloudPub has **no GO or NO-GO verdict yet**. Do not treat the PC probe as a substitute for the phone matrix.

## Boundary and configuration

The tested path was PC HTTPS client → CloudPub assigned `https://<assigned-host>.cloudpub.ru` → `http://127.0.0.1:8765` → authenticated FastAPI `/ws/chat` → local `CodexBridge` → local `codex app-server` over stdio. Uvicorn bound only to `127.0.0.1`, with one worker. `RC_AUTH_MODE=remote`, `RC_PUBLIC_ORIGIN` exactly matched the assigned HTTPS origin, and the built frontend was served by FastAPI. The application used a randomly generated temporary password with an Argon2id hash in the backend process environment. The password and temporary SQLite databases were outside the repository. The public `/health` route is informational; `/auth/session`, `/ready`, and `/ws/chat` remain session protected. No app-server port was published.

The PC has CloudPub GUI/client 3.0.2 installed. For this experiment, the official Windows CLI ZIP was extracted separately to `%TEMP%/rc-012-cloudpub/clo.exe`; `clo --version` reported `cloudpub-client 3.5.1056-20260831192056-stable`. The ZIP SHA-256 was `DB1238B3E3F01686D5856B7B6AD8095FE18803BA70E13FE7912FAA3E954FE904`. The existing CloudPub account configuration was used without copying its token into the repo. `codex --version` reported `codex-cli 0.160.0`. The public URL is an assigned CloudPub hostname; the full hostname and publication ID are omitted from tracked evidence.

Happ and `xray` processes were running, and the Windows user proxy setting was enabled. The user identified Happ **proxy mode** as the normal mode. The selected Happ server and whether the CloudPub CLI's traffic actually traversed that proxy were not established. Radmin VPN also had an active adapter, but the user said it is not the intended VPN condition. WinHTTP reported direct access. These observations do not prove the requested VPN-path behavior.

## Test matrix

| Required check | PC-side result | Physical phone/mobile-data result |
| --- | --- | --- |
| 1. Public HTTPS page | `GET /` and `/health` returned 200 through CloudPub. | Pending. |
| 2. Login | 200 with `__Host-rc_session`, `Secure`, `HttpOnly`, and `SameSite=Strict`; anonymous `/auth/session` returned 401. | Pending. |
| 3. WebSocket establishment | Authenticated WSS returned 101 and application `ready`; anonymous and wrong-Origin handshakes returned 403. | Pending. |
| 4. Backend/PC online state | Authenticated `/ready` returned 200; loopback `/health` returned 200. | Pending. |
| 5. Bidirectional messages | `list_projects` returned `project_list` over the public WSS connection. | Pending. |
| 6. Real prompt | A real Codex turn completed with 6 assistant deltas. | Pending. |
| 7. Long streamed response | An 80-line prompt completed with 239 assistant deltas. | Pending. |
| 8. Stop/interrupt | `stop_turn` produced `turn_completed: interrupted`. | Pending. |
| 9. Approval interaction | Not triggered safely in this run. | Pending if safely available. |
| 10. Network interruption/reconnect | A fresh authenticated WSS connection returned `ready`; mobile network interruption was not simulated. | Pending. |
| 11. Page reload | Not tested in a browser; the CLI established a fresh HTTP session and WSS connection. | Pending. |
| 12. Tunnel client restart | After an offline publication, `clo start <PoC GUID>` restored HTTPS 200. A controlled client-process restart while connected was not tested. | Pending. |
| 13. Normal Windows VPN | Happ and `xray` ran with Windows user proxy enabled. The chosen server and CloudPub CLI route through that proxy were not established. | Pending with user's normal Happ server. |
| 14. Long-lived stability | WSS remained responsive after 65 seconds idle with client pings. | Pending for at least 10 minutes of ordinary use. |

The repeatable PC probe is `backend/scripts/rc012_probe.py`. It reads `RC012_ORIGIN` and `RC012_PASSWORD` from the process environment. Optional `RC012_IDLE_SECONDS=65` checks idle responsiveness. It does not print credentials or response text. `RC012_WS_URL=ws://127.0.0.1:8765/ws/chat` was used only to compare a failing WSS flow against loopback during diagnosis; normal use should leave that override unset.

## Diagnosed failures

1. The first extended probe received `turn_completed` but the next prompt in the same socket did not produce `turn_started` within 45 seconds. The exact behavior reproduced through loopback in 15 seconds, so CloudPub was not responsible. `backend/app.py` left an in-flight `receive_json()` task after a turn finished; that task consumed the next message while the outer loop started a second read. A regression test failed before the fix and passed after it. The public-tunnel probe then completed two consecutive turns and Stop.
2. A later public request returned 503 while loopback `/health` remained 200, and the PoC publication was offline. Starting only that publication with `clo start <PoC GUID>` restored public 200. With no concurrent CloudPub CLI commands, the full probe and 65-second idle check passed. A controlled `clo -r ls` call while that agent ran was followed within five seconds by the agent process exiting and public `/health` returning 503; the same `ls` output had shown the service online. This establishes a reproducible **same-config CLI interference** observation, but the internal CloudPub mechanism was not proven. Avoid concurrent `clo` diagnostics against the same user configuration during a live session; use public health and the running process/log instead. This operational caveat needs confirmation during the eventual phone run.

## Resume the real-phone matrix

Use the [CloudPub quick start](https://cloudpub.ru/docs/) and [CLI reference](https://cloudpub.ru/docs/cli) for the current CLI and syntax. Keep the CloudPub token in its user configuration, never in a tracked file or command transcript. The registered `RC-012-FastAPI-PoC` service points only to `127.0.0.1:8765`. With the tunnel **stopped**, `clo ls` provides its GUID and assigned HTTPS URL. Set `RC_PUBLIC_ORIGIN` to that exact URL without a path or trailing slash. Generate your own password hash privately with `backend/scripts/hash_password.py`, run `npm run build` from `frontend/`, then start the backend from `backend/`:

```powershell
$env:RC_AUTH_MODE = 'remote'
$env:RC_PUBLIC_ORIGIN = 'https://<assigned-host>.cloudpub.ru'
$env:RC_PASSWORD_HASH = '<Argon2id hash supplied privately>'
uv run uvicorn app:app --host 127.0.0.1 --port 8765
```

In a second shell, start only the registered publication and leave that shell open:

```powershell
clo start <PoC GUID>
```

Do not run a second `clo` command with the same configuration while that publication is active. To test client restart, stop this foreground client and start the **same GUID** again, then record the phone's disconnect/reconnect and whether the URL remains unchanged. Avoid `clo run`: the account also contains unrelated publications, and `run` starts all registered services per the [CLI reference](https://cloudpub.ru/docs/cli).

On the physical phone, disable Wi-Fi and phone VPN, enable mobile data, and use the assigned ordinary HTTPS URL. Record the time, phone/browser, mobile carrier, selected Happ server, Happ proxy mode, and whether the Windows user proxy remains enabled. Check, in order: page load, login, online state, send and receive, long stream, Stop, approval if safely available, data interruption/reconnect, page reload, tunnel restart/recovery, and at least 10 minutes of ordinary connected use. Record each result and any HTTP status, WebSocket close code, or visible error. If an approval cannot be safely triggered, mark it untested rather than claiming a pass. Do not share passwords, cookies, CloudPub tokens, or unredacted request logs.

CloudPub gets **GO** only if this full phone-to-local-Codex flow works reliably with the user's normal Happ setup. If it fails, reproduce at the failing layer with one changed variable at a time and record a CloudPub **NO-GO** before trying ngrok; try Tailscale Funnel only after an ngrok NO-GO. The [RC-012 issue](https://github.com/4ertopolohh/remote-codex-chat/issues/13) defines the full acceptance matrix.
