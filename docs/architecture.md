# Backend architecture

The browser will talk to FastAPI. FastAPI owns one `CodexBridge` for its application
lifetime. `CodexBridge` owns a local `codex app-server` child process and uses the
validated RC-001 newline-delimited stdio transport. The PoC CLI imports that same
transport; there is one framing and JSON-RPC implementation.

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
