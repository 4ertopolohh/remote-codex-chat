# Backend architecture

## Authentication (RC-011)

`backend/auth.py` owns single-user password verification and server-side sessions. The
operator stores an Argon2id hash with the local `scripts/configure.py` CLI. The versioned
`backend/data/config.sqlite3` owns the hash, auth mode, exact public origin, and ordered
project allowlist. If absent, legacy environment values are imported once. Existing
SQLite configuration wins over stale legacy password/project values; explicit
`RC_AUTH_MODE` and `RC_PUBLIC_ORIGIN` override only runtime settings. Login creates a
random opaque ID in an `HttpOnly` cookie; SQLite stores its digest, a separate CSRF
token, and an absolute expiry. `/auth/session` gives the browser only the CSRF token,
and `/auth/logout` revokes the record and closes any active chat socket for it.
`/health` remains public; `/ready` and `/ws/chat` require a valid session. The WebSocket
also requires an exact configured `Origin` before it is accepted, and an expiry timer
ends long-lived connections. State-changing HTTP routes require exact `Origin`; logout
also requires the session's CSRF token. CORS is not enabled. The backend serves the
built frontend from the same origin when present; remote mode requires that build and
HTTPS. See `frontend/README.md` for setup and the local/remote cookie distinction.


The browser will talk to FastAPI. FastAPI owns one `CodexBridge` for its application
lifetime. `CodexBridge` owns a local `codex app-server` child process and uses the
validated RC-001 newline-delimited stdio transport. The PoC CLI imports that same
transport; there is one framing and JSON-RPC implementation.

The browser connects to `/ws/chat` on FastAPI. It sends validated chat controls and
answers to pending approval or user-input requests. The backend owns the project
allowlist in `config.sqlite3`. The first entry is the default. `RC_PROJECTS` and
`RC_PROJECT_PATH` are accepted only for one-time legacy import. The browser receives only
project IDs and names and selects an ID before creating a conversation. The server
resolves the corresponding directory immediately before `thread/start`; an unavailable
directory returns `project_unavailable`. The application WebSocket reports readiness, turn start,
assistant text deltas, agent status, and terminal completion or error. It never
exposes app-server request IDs, RPC envelopes, credentials, or a browser-supplied
working directory. One browser connection and one active turn are supported; this
serializes turns across all projects, including turns targeting the same project.

The bridge interface exposes lifecycle, thread creation/resume, turn start/interrupt,
and application-level events. Process launch, handshake, request IDs, protocol envelopes,
server requests, and stderr diagnostics remain inside the module. The browser
interface does not expose arbitrary JSON-RPC calls, Codex credentials, or the local
app-server listener.

Bridge-managed command and file approval requests receive opaque application IDs.
The browser sees only normalized request details and can answer `accept` or `decline`
once. Pending approvals time out or cancel on disconnect with `decline`; user-input
requests use the confirmed experimental answer shape when enabled and otherwise
receive method-not-found. User input is cancelled with an RPC error, never an invented
answer. Unknown server requests receive JSON-RPC method-not-found. Unrecognized notifications are ignored;
known event shapes are validated and malformed data terminates bridge readiness.

`/health` verifies the FastAPI process responds. `/ready` reflects whether the bridge
is initialized and its event pump is running. A failed app-server handshake fails
FastAPI startup. Application shutdown closes stdin, waits for the child, then
terminates or kills it if necessary.

The transport has an internal test seam at the child process command: tests run a
fake local subprocess and exercise the public `CodexBridge` interface. Real Codex
checks are separate and do not run in automated tests.

## Conversation recovery (RC-004)

`backend/conversation_store.py` keeps an application index in SQLite. The conversations
table contains the application conversation ID, selected project ID, Codex
thread ID, a short title derived from the first prompt, and creation/update timestamps.
Schema version 2 adds a `submissions` table. A browser-generated `request_id` is
reserved there before the non-idempotent `turn/start` call; replaying that ID cannot
start a second turn, including after a backend restart. The reservation is not proof
that Codex executed the turn. Existing version 1 databases migrate in place.
The file defaults to `backend/data/conversations.sqlite3` and can be set with
`RC_DATABASE_PATH`. The browser sees the application ID and metadata, never a project
filesystem path. Codex remains the execution and transcript source of truth.

The WebSocket accepts `new_conversation`, `list_conversations`, and
`select_conversation` alongside `submit_prompt`. Creating a conversation starts an
independent Codex thread and records its ID. Selecting one resolves its configured
project path, passes it to `thread/resume` through `CodexBridge`, and verifies the
effective cwd in the response. A mismatch rejects the conversation as unavailable.
The application then calls `thread/read` with `includeTurns: true` to rebuild the
text-only display from persisted user and agent items. Browser local storage remembers
only the selected application ID; on reload/reconnect it requests the list and selects
that ID. After a backend restart, the same SQLite file supplies the thread ID.
Tab session storage also retains the IDs of conversations whose submitted turn has
no observed terminal event. On reload, those conversations remain marked unknown
until the user reviews history and explicitly continues; the browser never replays
the prompt automatically.
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
Selecting a mode applies any model and reasoning preset returned by the runtime;
the user can then choose another supported value before starting the turn.
Missing or rejected experimental discovery produces an empty mode list and normal
chat continues. See [capability research](poc/RC-005-capabilities-research.md).
