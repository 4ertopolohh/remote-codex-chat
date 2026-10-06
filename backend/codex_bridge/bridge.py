"""Domain interface for the local Codex app-server process."""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._transport import (
    AppServerClient,
    AppServerError,
    AppServerProtocolError,
    AppServerRpcError,
    AppServerTerminatedError,
    AppServerUnavailableError,
    ServerNotification,
    ServerRequest,
)
from .usage import normalize_usage, normalize_usage_update


class BridgeError(RuntimeError):
    """Base application-level bridge failure."""


class CodexUnavailable(BridgeError):
    """Codex executable could not be launched."""


class InitializationFailed(BridgeError):
    """The local app-server did not complete its handshake."""


class ServerTerminated(BridgeError):
    """The app-server exited or lost its stdio connection."""


class MalformedProtocol(BridgeError):
    """The app-server sent invalid protocol data."""


class OperationFailed(BridgeError):
    """A supported domain operation failed."""


@dataclass(frozen=True)
class AgentMessageDelta:
    thread_id: str
    turn_id: str
    text: str


@dataclass(frozen=True)
class TurnCompleted:
    thread_id: str
    turn_id: str
    status: str


@dataclass(frozen=True)
class ThreadStatusChanged:
    thread_id: str
    status: str


@dataclass(frozen=True)
class RequestPending:
    id: str
    thread_id: str
    turn_id: str
    kind: str
    details: dict[str, object]


@dataclass(frozen=True)
class RequestFinished:
    id: str
    status: str


@dataclass(frozen=True)
class UsageChanged:
    rate_limits: dict[str, object]


@dataclass
class _PendingServerRequest:
    request_id: int | str
    kind: str
    question_ids: tuple[str, ...]
    question_options: dict[str, tuple[str, ...] | None]
    allow_other: frozenset[str]
    expiry: asyncio.Task[None]


@dataclass(frozen=True)
class ModelCapability:
    id: str
    model: str
    display_name: str
    reasoning_efforts: tuple[str, ...]
    default_reasoning_effort: str | None
    is_default: bool


@dataclass(frozen=True)
class CollaborationCapability:
    name: str
    mode: str
    model: str | None
    reasoning_effort: str | None


BridgeEvent = (
    AgentMessageDelta
    | TurnCompleted
    | ThreadStatusChanged
    | RequestPending
    | RequestFinished
)
_APPROVAL_METHODS = {
    "item/commandExecution/requestApproval": "command",
    "item/fileChange/requestApproval": "file_change",
}
_USER_INPUT_METHOD = "item/tool/requestUserInput"


class CodexBridge:
    """Own one local app-server and expose thread/turn behavior.

    Call start before operations, close at application shutdown. Server requests
    are brokered behind opaque application IDs. Events are consumed in arrival order.
    """

    def __init__(
        self,
        *,
        command: tuple[str, ...] | None = None,
        request_timeout: float = 60.0,
        experimental_features: bool = False,
        approval_timeout: float = 120.0,
    ):
        self._client = AppServerClient(command, request_timeout=request_timeout)
        self._request_timeout = request_timeout
        self._events: asyncio.Queue[BridgeEvent | BridgeError] = asyncio.Queue()
        self._usage_updates: asyncio.Queue[UsageChanged] = asyncio.Queue()
        self._pump: asyncio.Task[None] | None = None
        self._ready = False
        self._experimental_features = experimental_features
        self._approval_timeout = approval_timeout
        self._pending_requests: dict[str, _PendingServerRequest] = {}
        self._owned_threads: dict[str, Path] = {}

    @property
    def user_input_supported(self) -> bool:
        return self._experimental_features

    @property
    def ready(self) -> bool:
        return self._ready and self._pump is not None and not self._pump.done()

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        return self._client.stderr_tail

    async def start(self) -> None:
        if self.ready:
            return
        try:
            await self._client.initialize(
                client_name="remote_codex_chat",
                client_title="Remote Codex Chat",
                experimental_api=self._experimental_features,
            )
        except AppServerError as exc:
            await self._client.close()
            if isinstance(exc, AppServerUnavailableError):
                raise CodexUnavailable(str(exc)) from exc
            raise InitializationFailed(str(exc)) from exc
        self._ready = True
        self._pump = asyncio.create_task(
            self._read_events(), name="codex-bridge-events"
        )

    async def close(self) -> None:
        self._ready = False
        self._owned_threads.clear()
        await self.cancel_pending()
        await self._client.close()
        if self._pump is not None:
            self._pump.cancel()
            await asyncio.gather(self._pump, return_exceptions=True)

    def abort(self) -> None:
        """Stop a stalled app-server without waiting for protocol cooperation."""
        self._ready = False
        self._owned_threads.clear()
        if self._pump is not None:
            self._pump.cancel()
        self._client.abort()

    async def start_thread(
        self, project: Path, *, approval_policy: str | None = None
    ) -> str:
        if not project.is_dir():
            raise OperationFailed(f"Project directory does not exist: {project}")
        params = {"cwd": str(project.resolve())}
        if approval_policy is not None:
            params["approvalPolicy"] = approval_policy
        result = await self._request("thread/start", params)
        thread_id = self._nested_id(result, "thread")
        self._owned_threads[thread_id] = project.resolve()
        return thread_id

    async def resume_thread(self, thread_id: str, project: Path) -> str:
        if not project.is_dir():
            raise OperationFailed("Project directory is unavailable")
        trusted_cwd = project.resolve()
        result = await self._request(
            "thread/resume",
            {"threadId": thread_id, "excludeTurns": True, "cwd": str(trusted_cwd)},
        )
        actual_cwd = result.get("cwd") if isinstance(result, dict) else None
        if (
            not isinstance(actual_cwd, str)
            or not Path(actual_cwd).is_absolute()
            or Path(actual_cwd).resolve() != trusted_cwd
        ):
            raise OperationFailed("Resumed thread outside configured project")
        resumed_id = self._nested_id(result, "thread")
        self._owned_threads[resumed_id] = trusted_cwd
        return resumed_id

    async def restore_thread(
        self, thread_id: str, project: Path
    ) -> tuple[str, list[dict[str, str]]]:
        """Read history outside the main app-server, then claim its writer."""
        owned_project = self._owned_threads.get(thread_id)
        if owned_project is not None and owned_project != project.resolve():
            raise OperationFailed("Thread belongs to another project")
        reader = CodexBridge(
            command=self._client.command,
            request_timeout=min(self._request_timeout, 5.0),
            experimental_features=True,
        )
        try:
            await reader.start()
            try:
                async with asyncio.timeout(15.0):
                    try:
                        messages = await reader.read_messages(thread_id)
                    except OperationFailed as exc:
                        rpc_error = exc.__cause__
                        if not (
                            owned_project is None
                            and isinstance(rpc_error, AppServerRpcError)
                            and rpc_error.code == -32601
                        ):
                            raise
                        resumed_id = await reader.resume_thread(thread_id, project)
                        if resumed_id != thread_id:
                            raise OperationFailed("Resumed a different Codex thread")
                        messages = await reader._read_messages_full(thread_id)
            except TimeoutError as exc:
                raise OperationFailed("Timed out reading conversation history") from exc
        finally:
            try:
                await asyncio.wait_for(reader.close(), timeout=2.0)
            except asyncio.CancelledError:
                reader.abort()
                raise
            except (OSError, RuntimeError, TimeoutError) as exc:
                reader.abort()
                raise OperationFailed("Timed out or failed closing conversation history") from exc
        if owned_project is not None:
            return thread_id, messages
        return await self.resume_thread(thread_id, project), messages

    async def read_messages(self, thread_id: str) -> list[dict[str, str]]:
        """Project paged Codex items into the chat's text-only presentation."""
        messages: list[dict[str, str]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            params: dict[str, Any] = {"threadId": thread_id, "limit": 10}
            if cursor is not None:
                params["cursor"] = cursor
            result = await self._request("thread/items/list", params)
            entries = result.get("data") if isinstance(result, dict) else None
            if not isinstance(entries, list):
                raise MalformedProtocol("Missing thread item page")
            items = []
            for entry in entries:
                item = entry.get("item") if isinstance(entry, dict) else None
                if not isinstance(item, dict):
                    raise MalformedProtocol("Malformed thread item")
                items.append(item)
            messages.extend(self._project_messages(items))
            cursor = result.get("nextCursor")
            if cursor is None:
                return messages
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise MalformedProtocol("Invalid thread item cursor")
            seen_cursors.add(cursor)

    async def _read_messages_full(self, thread_id: str) -> list[dict[str, str]]:
        result = await self._request(
            "thread/read", {"threadId": thread_id, "includeTurns": True}
        )
        thread = result.get("thread") if isinstance(result, dict) else None
        turns = thread.get("turns") if isinstance(thread, dict) else None
        if not isinstance(turns, list):
            raise MalformedProtocol("Missing thread.turns in app-server response")
        items: list[dict[str, Any]] = []
        for turn in turns:
            turn_items = turn.get("items") if isinstance(turn, dict) else None
            if not isinstance(turn_items, list):
                raise MalformedProtocol("Missing turn.items in app-server response")
            items.extend(item for item in turn_items if isinstance(item, dict))
        return self._project_messages(items)

    @staticmethod
    def _project_messages(items: list[dict[str, Any]]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        for item in items:
            if item.get("type") == "userMessage":
                content = item.get("content")
                if isinstance(content, list):
                    text = "\n".join(
                        part["text"]
                        for part in content
                        if isinstance(part, dict)
                        and part.get("type") == "text"
                        and isinstance(part.get("text"), str)
                    )
                    if text:
                        messages.append({"role": "user", "text": text})
            elif item.get("type") == "agentMessage" and isinstance(
                item.get("text"), str
            ):
                messages.append({"role": "assistant", "text": item["text"]})
        return messages

    async def list_models(self) -> tuple[ModelCapability, ...]:
        models: list[ModelCapability] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while True:
            result = await self._request(
                "model/list", {"cursor": cursor} if cursor else {}
            )
            if not isinstance(result, dict) or not isinstance(result.get("data"), list):
                raise MalformedProtocol("Missing model catalog data")
            for item in result["data"]:
                if not isinstance(item, dict):
                    raise MalformedProtocol("Malformed model catalog entry")
                if item.get("hidden") is True:
                    continue
                model_id, model_name, display_name = (
                    item.get("id"),
                    item.get("model"),
                    item.get("displayName"),
                )
                efforts = item.get("supportedReasoningEfforts")
                if not all(
                    isinstance(v, str) and v
                    for v in (model_id, model_name, display_name)
                ) or not isinstance(efforts, list):
                    raise MalformedProtocol("Malformed model catalog entry")
                values: list[str] = []
                for effort in efforts:
                    value = (
                        effort.get("reasoningEffort")
                        if isinstance(effort, dict)
                        else None
                    )
                    if not isinstance(value, str) or not value:
                        raise MalformedProtocol("Malformed reasoning effort")
                    if value not in values:
                        values.append(value)
                default = item.get("defaultReasoningEffort")
                if default is not None and not isinstance(default, str):
                    raise MalformedProtocol("Malformed default reasoning effort")
                models.append(
                    ModelCapability(
                        model_id,
                        model_name,
                        display_name,
                        tuple(values),
                        default if default in values else None,
                        item.get("isDefault") is True,
                    )
                )
            cursor = result.get("nextCursor")
            if cursor is None:
                return tuple(models)
            if not isinstance(cursor, str) or not cursor or cursor in seen_cursors:
                raise MalformedProtocol("Invalid model catalog cursor")
            seen_cursors.add(cursor)

    async def list_collaboration_modes(self) -> tuple[CollaborationCapability, ...]:
        if not self._experimental_features:
            return ()
        try:
            result = await self._request("collaborationMode/list", {})
        except OperationFailed:
            return ()
        if not isinstance(result, dict) or not isinstance(result.get("data"), list):
            return ()
        modes = []
        for item in result["data"]:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("name"), str)
                or not isinstance(item.get("mode"), str)
            ):
                continue
            model = item.get("model")
            effort = item.get("reasoning_effort")
            modes.append(
                CollaborationCapability(
                    item["name"],
                    item["mode"],
                    model if isinstance(model, str) else None,
                    effort if isinstance(effort, str) else None,
                )
            )
        return tuple(modes)

    async def read_usage(self) -> dict[str, object]:
        if not self.ready:
            raise ServerTerminated("Codex bridge is not ready")
        try:
            return normalize_usage(await self._client.request("account/rateLimits/read", {}, timeout=10))
        except AppServerRpcError as exc:
            if exc.code == -32601:
                return {"status": "unsupported", "rate_limits": None, "rate_limits_by_id": {}, "ordinary_usage_allowed": None}
            raise OperationFailed(str(exc)) from exc
        except AppServerError as exc:
            raise self._translate(exc) from exc

    async def next_usage_update(self) -> UsageChanged:
        return await self._usage_updates.get()

    async def start_turn(
        self,
        thread_id: str,
        prompt: str,
        *,
        model: str | None = None,
        effort: str | None = None,
        collaboration_mode: str | None = None,
    ) -> str:
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [{"type": "text", "text": prompt}],
        }
        if model is not None:
            params["model"] = model
        if effort is not None:
            params["effort"] = effort
        if collaboration_mode is not None:
            if not self._experimental_features:
                raise OperationFailed("Experimental collaboration is disabled")
            if model is None:
                raise OperationFailed("Collaboration mode requires a selected model")
            params["collaborationMode"] = {
                "mode": collaboration_mode,
                "settings": {
                    "model": model,
                    "reasoning_effort": effort,
                    "developer_instructions": None,
                },
            }
        result = await self._request(
            "turn/start",
            params,
        )
        return self._nested_id(result, "turn")

    async def steer_turn(self, thread_id: str, turn_id: str, prompt: str) -> None:
        result = await self._request(
            "turn/steer",
            {
                "threadId": thread_id,
                "expectedTurnId": turn_id,
                "input": [{"type": "text", "text": prompt}],
            },
        )
        if not isinstance(result, dict) or result.get("turnId") != turn_id:
            raise MalformedProtocol("Unexpected steered turn ID")

    async def interrupt_turn(self, thread_id: str, turn_id: str) -> None:
        params = {"threadId": thread_id, "turnId": turn_id}
        for attempt in range(3):
            try:
                await self._request("turn/interrupt", params)
                return
            except OperationFailed as exc:
                rpc_error = exc.__cause__
                # Codex can acknowledge turn/start before the turn is interruptible.
                if not (
                    attempt < 2
                    and isinstance(rpc_error, AppServerRpcError)
                    and rpc_error.code == -32600
                    and rpc_error.message == "no active turn to interrupt"
                ):
                    raise
                await asyncio.sleep(0.2)

    async def next_event(self, *, timeout: float | None = None) -> BridgeEvent:
        if not self.ready and self._events.empty():
            raise ServerTerminated("Codex bridge is not ready")
        try:
            event = await asyncio.wait_for(self._events.get(), timeout=timeout)
        except TimeoutError as exc:
            raise OperationFailed("Timed out waiting for a Codex event") from exc
        if isinstance(event, BridgeError):
            raise event
        return event

    async def answer_request(self, pending_id: str, decision: str) -> bool:
        if decision not in {"accept", "decline"}:
            return False
        pending = self._pending_requests.get(pending_id)
        if pending is None or pending.kind == "user_input":
            return False
        await self._resolve(pending_id, {"decision": decision}, "completed")
        return True

    async def answer_user_input(
        self, pending_id: str, answers: dict[str, list[str]]
    ) -> bool:
        pending = self._pending_requests.get(pending_id)
        if (
            pending is None
            or pending.kind != "user_input"
            or set(answers) != set(pending.question_ids)
        ):
            return False
        if any(
            not values
            or any(
                not isinstance(value, str) or not value.strip() or len(value) > 10000
                for value in values
            )
            for values in answers.values()
        ):
            return False
        for question_id, values in answers.items():
            options = pending.question_options[question_id]
            if (
                options is not None
                and question_id not in pending.allow_other
                and any(value not in options for value in values)
            ):
                return False
        await self._resolve(
            pending_id,
            {"answers": {key: {"answers": values} for key, values in answers.items()}},
            "completed",
        )
        return True

    async def cancel_pending(self) -> None:
        for pending_id in tuple(self._pending_requests):
            await self.cancel_request(pending_id)

    async def cancel_request(self, pending_id: str) -> None:
        pending = self._pending_requests.get(pending_id)
        if pending is not None:
            result = {"decision": "decline"} if pending.kind != "user_input" else None
            await self._resolve(pending_id, result, "cancelled")

    async def _resolve(
        self, pending_id: str, result: dict[str, object] | None, status: str
    ) -> None:
        pending = self._pending_requests.pop(pending_id, None)
        if pending is None:
            return
        if pending.expiry is not asyncio.current_task():
            pending.expiry.cancel()
        final_status = status
        try:
            if result is None:
                await self._client.respond_error(
                    pending.request_id, code=-32603, message="User input unavailable"
                )
            else:
                await self._client.respond(pending.request_id, result)
        except AppServerError as exc:
            final_status = "cancelled"
            if self.ready:
                raise self._translate(exc) from exc
        finally:
            self._events.put_nowait(RequestFinished(pending_id, final_status))

    async def _expire(self, pending_id: str) -> None:
        try:
            await asyncio.sleep(self._approval_timeout)
            pending = self._pending_requests.get(pending_id)
            if pending is not None:
                result = (
                    {"decision": "decline"} if pending.kind != "user_input" else None
                )
                try:
                    await self._resolve(pending_id, result, "expired")
                except BridgeError:
                    pass
        except asyncio.CancelledError:
            pass

    async def _register_server_request(self, incoming: ServerRequest) -> None:
        kind = _APPROVAL_METHODS.get(incoming.method)
        if (
            kind is None
            and incoming.method == _USER_INPUT_METHOD
            and self.user_input_supported
        ):
            kind = "user_input"
        if kind is None:
            await self._client.respond_error(
                incoming.request_id, code=-32601, message="Unsupported client request"
            )
            return
        params = incoming.params
        thread_id = self._string(params, "threadId")
        turn_id = self._string(params, "turnId")
        if not thread_id or not turn_id:
            await self._client.respond_error(
                incoming.request_id, code=-32602, message="Malformed client request"
            )
            return
        fields = (
            ("command", "reason", "kind")
            if kind == "command"
            else ("reason",)
        )
        details: dict[str, object] = {
            key: params[key] for key in fields if isinstance(params.get(key), str)
        }
        question_ids: tuple[str, ...] = ()
        question_options: dict[str, tuple[str, ...] | None] = {}
        allow_other: set[str] = set()
        if kind == "user_input":
            questions = params.get("questions")
            if not isinstance(questions, list) or not questions or len(questions) > 3:
                await self._client.respond_error(
                    incoming.request_id,
                    code=-32602,
                    message="Malformed user input request",
                )
                return
            normalized = []
            for question in questions:
                if not isinstance(question, dict) or not all(
                    isinstance(question.get(key), str) and question[key]
                    for key in ("id", "header", "question")
                ):
                    await self._client.respond_error(
                        incoming.request_id,
                        code=-32602,
                        message="Malformed user input request",
                    )
                    return
                options = question.get("options")
                if options is not None and (
                    not isinstance(options, list)
                    or any(
                        not isinstance(option, dict)
                        or not isinstance(option.get("label"), str)
                        or not isinstance(option.get("description"), str)
                        for option in options
                    )
                ):
                    await self._client.respond_error(
                        incoming.request_id,
                        code=-32602,
                        message="Malformed user input request",
                    )
                    return
                normalized.append(
                    {
                        "id": question["id"],
                        "header": question["header"],
                        "question": question["question"],
                        "options": options,
                        "is_other": question.get("isOther") is True,
                        "is_secret": question.get("isSecret") is True,
                    }
                )
                question_options[question["id"]] = (
                    tuple(option["label"] for option in options)
                    if options is not None
                    else None
                )
                if question.get("isOther") is True:
                    allow_other.add(question["id"])
            question_ids = tuple(item["id"] for item in normalized)
            if len(set(question_ids)) != len(question_ids):
                await self._client.respond_error(
                    incoming.request_id, code=-32602, message="Duplicate question ID"
                )
                return
            details = {"questions": normalized}
        pending_id = secrets.token_urlsafe(24)
        self._pending_requests[pending_id] = _PendingServerRequest(
            incoming.request_id,
            kind,
            question_ids,
            question_options,
            frozenset(allow_other),
            asyncio.create_task(self._expire(pending_id)),
        )
        self._events.put_nowait(
            RequestPending(pending_id, thread_id, turn_id, kind, details)
        )

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        if not self.ready:
            raise ServerTerminated("Codex bridge is not ready")
        try:
            return await self._client.request(method, params)
        except AppServerError as exc:
            raise self._translate(exc) from exc

    async def _read_events(self) -> None:
        try:
            while True:
                incoming = await self._client.next_event()
                if isinstance(incoming, ServerRequest):
                    await self._register_server_request(incoming)
                    continue
                event = self._map_notification(incoming)
                if isinstance(event, UsageChanged):
                    self._usage_updates.put_nowait(event)
                elif event is not None:
                    self._events.put_nowait(event)
        except asyncio.CancelledError:
            raise
        except AppServerError as exc:
            self._ready = False
            for pending_id, pending in tuple(self._pending_requests.items()):
                pending.expiry.cancel()
                self._pending_requests.pop(pending_id, None)
                self._events.put_nowait(RequestFinished(pending_id, "cancelled"))
            self._events.put_nowait(self._translate(exc))
            await self._client.close()

    @staticmethod
    def _string(params: dict[str, Any], key: str) -> str | None:
        value = params.get(key)
        return value if isinstance(value, str) else None

    def _map_notification(self, event: ServerNotification) -> BridgeEvent | UsageChanged | None:
        params = event.params
        if event.method == "account/rateLimits/updated":
            snapshot = normalize_usage_update(params)
            return UsageChanged(snapshot) if snapshot is not None else None
        thread_id = self._string(params, "threadId")
        if event.method == "item/agentMessage/delta":
            turn_id = self._string(params, "turnId")
            delta = self._string(params, "delta")
            if thread_id is None or turn_id is None or delta is None:
                raise AppServerProtocolError("Malformed agent message delta")
            return AgentMessageDelta(thread_id, turn_id, delta)
        if event.method == "turn/completed":
            turn = params.get("turn")
            if thread_id is None or not isinstance(turn, dict):
                raise AppServerProtocolError("Malformed turn completion")
            turn_id = self._string(turn, "id")
            status = self._string(turn, "status")
            if turn_id is None or status is None:
                raise AppServerProtocolError("Malformed turn completion")
            return TurnCompleted(thread_id, turn_id, status)
        if event.method == "thread/status/changed":
            status = params.get("status")
            if thread_id is None or not isinstance(status, dict):
                raise AppServerProtocolError("Malformed thread status")
            status_type = self._string(status, "type")
            if status_type is None:
                raise AppServerProtocolError("Malformed thread status")
            return ThreadStatusChanged(thread_id, status_type)
        return None

    @staticmethod
    def _nested_id(result: Any, key: str) -> str:
        nested = result.get(key) if isinstance(result, dict) else None
        value = nested.get("id") if isinstance(nested, dict) else None
        if not isinstance(value, str):
            raise MalformedProtocol(f"Missing {key}.id in app-server response")
        return value

    @staticmethod
    def _translate(exc: AppServerError) -> BridgeError:
        if isinstance(exc, AppServerProtocolError):
            return MalformedProtocol(str(exc))
        if isinstance(exc, AppServerRpcError):
            return OperationFailed(str(exc))
        if isinstance(exc, AppServerTerminatedError):
            return ServerTerminated(str(exc))
        return OperationFailed(str(exc))
