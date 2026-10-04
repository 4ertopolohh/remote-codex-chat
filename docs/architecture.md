# Backend architecture

The browser will talk to FastAPI. FastAPI owns one `CodexBridge` for its application
lifetime. `CodexBridge` owns a local `codex app-server` child process and uses the
validated RC-001 newline-delimited stdio transport. The PoC CLI imports that same
transport; there is one framing and JSON-RPC implementation.

The browser connects to `/ws/chat` on FastAPI. Its only command is a validated
`submit_prompt` with text; the backend selects the project from `RC_PROJECT_PATH`
or the repository root. The application WebSocket reports readiness, turn start,
assistant text deltas, agent status, and terminal completion or error. It never
exposes app-server request IDs, RPC envelopes, credentials, or a browser-supplied
working directory. One browser connection and one active turn are supported.

The bridge interface exposes lifecycle, thread creation/resume, turn start/interrupt,
and application-level events. Process launch, handshake, request IDs, protocol envelopes,
server requests, and stderr diagnostics remain inside the module. The future browser
interface must not expose arbitrary JSON-RPC calls, Codex credentials, or the local
app-server listener.

Until an approval user interface exists, bridge-managed command and file approval
requests receive `decline` and produce an `ApprovalDeclined` event. Unknown server
requests receive JSON-RPC method-not-found. Unrecognized notifications are ignored;
known event shapes are validated and malformed data terminates bridge readiness.

`/health` verifies the FastAPI process responds. `/ready` reflects whether the bridge
is initialized and its event pump is running. A failed app-server handshake fails
FastAPI startup. Application shutdown closes stdin, waits for the child, then
terminates or kills it if necessary.

The transport has an internal test seam at the child process command: tests run a
fake local subprocess and exercise the public `CodexBridge` interface. Real Codex
checks are separate and do not run in automated tests.

## Conversation recovery (RC-004)

`backend/conversation_store.py` keeps an application index in SQLite. Schema version 1
contains only application conversation ID, fixed single-project ID (`default`), Codex
thread ID, a short title derived from the first prompt, and creation/update timestamps.
The file defaults to `backend/data/conversations.sqlite3` and can be set with
`RC_DATABASE_PATH`. The browser sees the application ID and metadata, never a project
filesystem path. Codex remains the execution and transcript source of truth.

The WebSocket accepts `new_conversation`, `list_conversations`, and
`select_conversation` alongside `submit_prompt`. Creating a conversation starts an
independent Codex thread and records its ID. Selecting one calls `thread/resume`
through `CodexBridge`, then `thread/read` with `includeTurns: true` to rebuild the
text-only display from persisted user and agent items. Browser local storage remembers
only the selected application ID; on reload/reconnect it requests the list and selects
that ID. After a backend restart, the same SQLite file supplies the thread ID.
Unavailable or deleted Codex threads return `thread_unavailable` and the user can
start another conversation. Missing application IDs return `conversation_not_found`.

The installed `codex-cli 0.160.0` returned full turns from `thread/read` across a
process restart. Experimental pagination methods also worked with opt-in, but are not
needed for this small UI. See [protocol research](poc/RC-003-thread-history-research.md)
for current upstream caveats. Long conversations may eventually need native
pagination; there is no SQLite transcript cache.

## Runtime controls (RC-005)

`CodexBridge.list_models()` reads every page of `model/list` and exposes visible
models with stable IDs, wire model names, per-model reasoning choices, and the
runtime default. The browser requests normalized capabilities over `/ws/chat` on
connection or with Refresh models. The backend refreshes the model catalog before
each new turn and rejects unavailable model or reasoning selections. The browser
stores the selected model and effort locally and falls back to the runtime default
when a refreshed catalog removes either value.

`submit_prompt` starts a new turn. During a confirmed active turn, `steer_turn`
adds text to that turn through `turn/steer`, while `stop_turn` requests
`turn/interrupt` and waits for `turn/completed`. The browser enables Stop and Steer
only after `turn_started` and disables both while a stop request is pending.

Collaboration modes require `RC_EXPERIMENTAL_FEATURES=1`. Without that explicit
setting, the bridge does not opt into the experimental Codex protocol or query
`collaborationMode/list`. With it, the UI shows only modes returned by the runtime.
Missing or rejected experimental discovery produces an empty mode list and normal
chat continues. See [capability research](poc/RC-005-capabilities-research.md).
