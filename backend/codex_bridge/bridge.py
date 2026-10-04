"""Domain interface for the local Codex app-server process."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._transport import (
    AppServerClient,
    AppServerError,
    AppServerProtocolError,
    AppServerRpcError,
    ServerNotification,
    ServerRequest,
)


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
class ApprovalDeclined:
    thread_id: str | None
    kind: str


BridgeEvent = AgentMessageDelta | TurnCompleted | ThreadStatusChanged | ApprovalDeclined
_APPROVAL_METHODS = {
    "item/commandExecution/requestApproval": "command",
    "item/fileChange/requestApproval": "file change",
}


class CodexBridge:
    """Own one local app-server and expose thread/turn behavior.

    Call start before operations, close at application shutdown. Approval requests
    are declined until a user decision interface exists. Events are consumed in
    arrival order; unknown notifications are ignored.
    """

    def __init__(
        self, *, command: tuple[str, ...] | None = None, request_timeout: float = 60.0
    ):
        self._client = AppServerClient(command, request_timeout=request_timeout)
        self._events: asyncio.Queue[BridgeEvent | BridgeError] = asyncio.Queue()
        self._pump: asyncio.Task[None] | None = None
        self._ready = False

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
            )
        except AppServerError as exc:
            await self._client.close()
            if "Cannot start" in str(exc):
                raise CodexUnavailable(str(exc)) from exc
            raise InitializationFailed(str(exc)) from exc
        self._ready = True
        self._pump = asyncio.create_task(
            self._read_events(), name="codex-bridge-events"
        )

    async def close(self) -> None:
        self._ready = False
        await self._client.close()
        if self._pump is not None:
            self._pump.cancel()
            await asyncio.gather(self._pump, return_exceptions=True)

    async def start_thread(self, project: Path) -> str:
        if not project.is_dir():
            raise OperationFailed(f"Project directory does not exist: {project}")
        result = await self._request("thread/start", {"cwd": str(project.resolve())})
        return self._nested_id(result, "thread")

    async def resume_thread(self, thread_id: str) -> str:
        result = await self._request(
            "thread/resume", {"threadId": thread_id, "excludeTurns": True}
        )
        return self._nested_id(result, "thread")

    async def start_turn(self, thread_id: str, prompt: str) -> str:
        result = await self._request(
            "turn/start",
            {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]},
        )
        return self._nested_id(result, "turn")

    async def interrupt_turn(self, thread_id: str, turn_id: str) -> None:
        await self._request(
            "turn/interrupt", {"threadId": thread_id, "turnId": turn_id}
        )

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
                    kind = _APPROVAL_METHODS.get(incoming.method)
                    if kind is None:
                        await self._client.respond_error(
                            incoming.request_id,
                            code=-32601,
                            message="Unsupported client request",
                        )
                    else:
                        await self._client.respond(
                            incoming.request_id, {"decision": "decline"}
                        )
                        self._events.put_nowait(
                            ApprovalDeclined(
                                self._string(incoming.params, "threadId"), kind
                            )
                        )
                    continue
                event = self._map_notification(incoming)
                if event is not None:
                    self._events.put_nowait(event)
        except asyncio.CancelledError:
            raise
        except AppServerError as exc:
            self._ready = False
            self._events.put_nowait(self._translate(exc))

    @staticmethod
    def _string(params: dict[str, Any], key: str) -> str | None:
        value = params.get(key)
        return value if isinstance(value, str) else None

    def _map_notification(self, event: ServerNotification) -> BridgeEvent | None:
        params = event.params
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
        if "exited" in str(exc) or "connection" in str(exc):
            return ServerTerminated(str(exc))
        return OperationFailed(str(exc))
