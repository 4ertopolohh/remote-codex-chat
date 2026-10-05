# RC-013: reconnect and failure recovery

Checked on 2026-10-05. This file records automated evidence from the Windows workspace. It is not a physical-phone or live-tunnel verification. RC-012 still has no phone-side GO, so the network acceptance gate for RC-013 remains open.

## Recovery contract

| Failure class | Detection | State shown / safe action | Evidence |
| --- | --- | --- | --- |
| Backend unavailable or tunnel outage | Session fetch or WebSocket fails | Login page reports unreachable server; an authenticated page shows Offline and retries with exponential delay capped at 30 seconds. Check backend/tunnel and retry. | Frontend connection test; live outage pending. |
| WebSocket loss during idle | Close event | Offline then Reconnecting; reconnect restores project and conversation history. | Frontend reconnect and reload tests. |
| WebSocket or phone network loss during a turn | Close event before terminal event | Turn is **unknown** across reconnect/reload. Prompt is never replayed. Review restored history before acknowledging and continuing. | Frontend fault injection; phone network toggle pending. |
| Reload during a turn | Tab's WebSocket closes; tab session storage retains conversation ID | Same unknown state after history reload; no automatic prompt replay. | Frontend reload fault injection. |
| Duplicate submission / lost acknowledgement | Repeated `request_id` | FastAPI rejects `duplicate_submission` before a second `start_turn`. IDs are reserved in SQLite before the non-idempotent bridge call and survive backend restart. New sends use new UUIDs. | Backend WebSocket restart test and frontend send test. |
| Codex executable/startup failure | Backend startup or bridge not ready | Startup cannot claim readiness; a live socket reports `codex_unavailable`. Check Codex and restart backend. | Existing bridge and WebSocket tests. |
| App-server crash during a turn | Bridge event read raises | Drain releases the single-chat lock; reconnect can proceed, and unknown turn remains honest. Check backend/Codex before continuing. | New backend crash fault-injection test. |
| App-server crash while idle | Bridge readiness false on new WebSocket | `codex_unavailable`; restart backend. | Existing unavailable bridge test. |
| Malformed protocol or turn failure | Bridge error or terminal `failed` | Safe error code or known failed terminal state; no internal exception text is sent to browser. Check backend, then review conversation. | Existing bridge/WebSocket tests. |
| Interrupt | Terminal `interrupted` | Known interrupted state; Stop is not replayed. | Existing Stop test. |
| Unavailable model, reasoning, mode | Preflight error | Rejected prompt is removed; refresh/select a listed capability and send again. | Existing capability tests. |
| Expired or revoked session | WebSocket close 4401 or session check 401 | Sign-in screen; reauthenticate. | Existing auth tests. |
| Pending approval or user input at disconnect | WebSocket close; backend `cancel_pending` | UI disables the old request and labels its outcome unknown. Backend attempts decline for approval or unavailable error for user input. A successful prior response may have reached Codex, so UI does not claim cancellation. | Existing approval disconnect test; new frontend request test. |
| Stale conversation/thread | Selection returns `conversation_not_found` or `thread_unavailable` | Old transcript is cleared; start a new conversation. | Existing recovery and frontend tests. |

The SQLite submission record is a conservative replay fence, not proof that Codex executed a turn. A crash between ID reservation and the Codex response leaves the outcome unknown. A fresh ID represents a new deliberate action after the user reviews history. Legacy clients that omit `request_id` retain the earlier protocol behavior; the shipped browser always supplies it.

## Verification and outstanding real-world checks

- `cd backend && uv run pytest -q`: 60 passed.
- `cd backend && uv run ruff check .`: passed.
- `cd frontend && npm test`: 32 passed.
- `cd frontend && npm run lint && npm run build`: passed.
- Windows Python subprocess tests emitted pre-existing async transport cleanup warnings; no test failed.
- The physical phone, mobile-data toggle, normal Happ VPN mode, CloudPub outage/restart, and long-lived public WebSocket path have **not** been exercised for RC-013. Complete the [RC-012 phone matrix](RC-012-remote-access.md) before claiming production network recovery or closing this ticket.
