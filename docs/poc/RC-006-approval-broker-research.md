# RC-006 — approval broker protocol and design

Checked 2026-10-05 with `codex-cli 0.160.0` (`codex app-server generate-ts --out <temporary directory>`) and OpenAI's generated [ServerRequest union](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/ServerRequest.ts).

The confirmed server requests are `item/commandExecution/requestApproval`, `item/fileChange/requestApproval`, and experimental `item/tool/requestUserInput`. Command requests may contain `command`, `cwd`, `reason`, `kind`, and `threadId`/`turnId`; file requests contain `reason`, optional `grantRoot`, and thread/turn IDs. The browser receives only display fields, never the Codex RPC ID or raw params. [Command params](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/CommandExecutionRequestApprovalParams.ts), [file params](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/FileChangeRequestApprovalParams.ts).

Both approval responses accept `{ "decision": "accept" | "decline" }`; this application intentionally offers only those two choices. [Command response](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/CommandExecutionRequestApprovalResponse.ts), [file response](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/FileChangeRequestApprovalResponse.ts).

The experimental user-input request carries `questions` with IDs, text, optional options, `isOther`, and `isSecret`. The response is `{ "answers": { "<questionId>": { "answers": ["<text>"] } } }`. It is exposed only when experimental features are enabled. [Params](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/ToolRequestUserInputParams.ts), [question](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/ToolRequestUserInputQuestion.ts), [response](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/schema/typescript/v2/ToolRequestUserInputResponse.ts).

## State machine and test seams

The `CodexBridge` module owns `pending → resolved | expired | cancelled`. Registration creates an unguessable application ID. Answering removes it before writing to app-server, so concurrent and duplicate answers cannot write twice. A deadline expires approvals by sending `decline`; connection loss cancels approvals with `decline`. User input expires/cancels with a JSON-RPC error because an empty answer can misrepresent user intent. Process death clears pending IDs. Terminal status events let the browser distinguish outcomes.

The public `CodexBridge.next_event`/`answer_request` interface and `/ws/chat` are the agreed test seams. Reconnect starts with no prior request authority; the existing disconnect policy interrupts the turn. The installed stable schema includes the experimental user-input type, but normal application operation reports it as unsupported until explicitly opted in. Real user-input generation depends on a safely triggerable experimental turn and is not inferred from schema presence.

`reason` and `grantRoot` are optional on file approvals, and the request never contains a list of changed files. The browser warns of this incomplete scope and requires acknowledgement before enabling Approve for every file approval. The request remains answerable with `decline` at any time. A command request without `command` cannot be approved from the browser because its action cannot be shown.

## Real disposable-repo check

On 2026-10-05, `python -m poc.rc006_real_approval_check` ran against real `codex-cli 0.160.0`. The app-server emitted one `item/commandExecution/requestApproval` for PowerShell `echo RC006_OK`. The broker answered `accept`, the turn completed, and `git status --short` in the temporary repo was empty. The script accepts only that exact command and declines any other request. The temporary repo was deleted when the check finished.

No real experimental `item/tool/requestUserInput` turn was triggered. Its response shape is verified by the installed generated schema and a simulated app-server exchange; the default application capability remains `unsupported`.
