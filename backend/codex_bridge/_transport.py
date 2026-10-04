from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self

JsonObject = dict[str, Any]
RequestId = int | str


class AppServerError(RuntimeError):
    """Base error for the PoC app-server transport."""


class AppServerProtocolError(AppServerError):
    """Raised when app-server returns malformed JSON or an unexpected envelope."""


class AppServerUnavailableError(AppServerError):
    """Raised when the Codex executable cannot be launched."""


class AppServerTerminatedError(AppServerError):
    """Raised when the app-server exits or loses its stdio connection."""


class AppServerRpcError(AppServerError):
    """Raised when app-server returns a JSON-RPC error response."""

    def __init__(
        self,
        method: str,
        code: int | None,
        message: str,
        data: Any = None,
    ) -> None:
        super().__init__(f"{method} failed ({code}): {message}")
        self.method = method
        self.code = code
        self.message = message
        self.data = data


@dataclass(frozen=True)
class ServerNotification:
    method: str
    params: JsonObject


@dataclass(frozen=True)
class ServerRequest:
    request_id: RequestId
    method: str
    params: JsonObject


IncomingEvent = ServerNotification | ServerRequest


@dataclass
class _PendingRequest:
    method: str
    future: asyncio.Future[Any]


class AppServerClient:
    """Minimal newline-delimited JSON client for `codex app-server` over stdio."""

    def __init__(
        self,
        command: Sequence[str] | None = None,
        *,
        request_timeout: float = 60.0,
        stderr_tail_lines: int = 100,
    ) -> None:
        self._command = tuple(
            command or ("codex", "app-server", "--listen", "stdio://")
        )
        self._request_timeout = request_timeout
        self._stderr_tail: deque[str] = deque(maxlen=stderr_tail_lines)
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._write_lock = asyncio.Lock()
        self._next_request_id = 1
        self._pending: dict[RequestId, _PendingRequest] = {}
        self._events: asyncio.Queue[IncomingEvent | Exception] = asyncio.Queue()
        self._closed = False
        self._terminal_error: Exception | None = None

    @property
    def command(self) -> tuple[str, ...]:
        return self._command

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        return tuple(self._stderr_tail)

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    async def start(self) -> None:
        if self._closed:
            raise AppServerError("codex app-server client is closed")
        if self._process is not None:
            return

        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise AppServerUnavailableError(
                f"Cannot start {self._command[0]!r}. Ensure Codex CLI is installed and on PATH."
            ) from exc

        self._reader_task = asyncio.create_task(
            self._read_stdout(), name="codex-app-server-stdout"
        )
        self._stderr_task = asyncio.create_task(
            self._read_stderr(), name="codex-app-server-stderr"
        )

    async def initialize(
        self,
        *,
        client_name: str = "remote_codex_chat_poc",
        client_title: str = "Remote Codex Chat PoC",
        client_version: str = "0.1.0",
        experimental_api: bool = False,
    ) -> JsonObject:
        await self.start()
        result = await self.request(
            "initialize",
            {
                "clientInfo": {
                    "name": client_name,
                    "title": client_title,
                    "version": client_version,
                },
                "capabilities": {"experimentalApi": experimental_api},
            },
        )
        if not isinstance(result, dict):
            raise AppServerProtocolError("initialize returned a non-object result")
        await self.notify("initialized")
        return result

    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        await self.start()
        if self._terminal_error is not None:
            raise self._terminal_error
        loop = asyncio.get_running_loop()
        request_id = self._next_request_id
        self._next_request_id += 1
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = _PendingRequest(method=method, future=future)

        message: JsonObject = {"method": method, "id": request_id}
        if params is not None:
            message["params"] = dict(params)

        try:
            await self._send(message)
            return await asyncio.wait_for(
                future,
                timeout=self._request_timeout if timeout is None else timeout,
            )
        except TimeoutError as exc:
            if not future.done():
                future.cancel()
            raise AppServerError(f"Timed out waiting for {method}") from exc
        finally:
            self._pending.pop(request_id, None)

    async def notify(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> None:
        await self.start()
        message: JsonObject = {"method": method}
        if params is not None:
            message["params"] = dict(params)
        await self._send(message)

    async def respond(
        self, request_id: RequestId, result: Mapping[str, Any] | None = None
    ) -> None:
        await self._send({"id": request_id, "result": dict(result or {})})

    async def respond_error(
        self,
        request_id: RequestId,
        *,
        code: int,
        message: str,
        data: Any = None,
    ) -> None:
        error: JsonObject = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        await self._send({"id": request_id, "error": error})

    async def next_event(self, *, timeout: float | None = None) -> IncomingEvent:
        if self._terminal_error is not None and self._events.empty():
            raise self._terminal_error
        if timeout is None:
            event = await self._events.get()
        else:
            try:
                event = await asyncio.wait_for(self._events.get(), timeout=timeout)
            except TimeoutError as exc:
                raise AppServerError(
                    "Timed out waiting for an app-server event"
                ) from exc
        if isinstance(event, Exception):
            raise event
        return event

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        process = self._process
        if process is None:
            return

        if process.stdin is not None and not process.stdin.is_closing():
            process.stdin.close()
            try:
                await process.stdin.wait_closed()
            except (BrokenPipeError, ConnectionResetError):
                pass

        try:
            await asyncio.wait_for(process.wait(), timeout=2.0)
        except TimeoutError:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except TimeoutError:
                process.kill()
                await process.wait()

        tasks = [
            task for task in (self._reader_task, self._stderr_task) if task is not None
        ]
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=1.0
            )
        except TimeoutError:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        self._fail_pending(
            AppServerError(f"codex app-server exited with code {process.returncode}")
        )

    async def _send(self, message: Mapping[str, Any]) -> None:
        if self._terminal_error is not None:
            raise self._terminal_error
        process = self._process
        if process is None or process.stdin is None:
            raise AppServerTerminatedError("codex app-server is not running")
        if process.returncode is not None:
            raise AppServerTerminatedError(
                self._process_exit_message(process.returncode)
            )

        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        async with self._write_lock:
            try:
                process.stdin.write(payload + b"\n")
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                raise AppServerTerminatedError(
                    "Lost stdin connection to codex app-server"
                ) from exc

    async def _read_stdout(self) -> None:
        process = self._process
        assert process is not None and process.stdout is not None

        try:
            while True:
                raw_line = await process.stdout.readline()
                if not raw_line:
                    break

                try:
                    message = json.loads(raw_line)
                except json.JSONDecodeError:
                    self._fail_all(
                        AppServerProtocolError(
                            "Invalid JSON from app-server stdout: "
                            + raw_line.decode("utf-8", "replace").rstrip()
                        )
                    )
                    return

                if not isinstance(message, dict):
                    self._fail_all(
                        AppServerProtocolError(
                            "app-server emitted a non-object JSON value"
                        )
                    )
                    return

                self._route_message(message)
        finally:
            if not self._closed:
                returncode = process.returncode
                if returncode is None:
                    returncode = await process.wait()
                self._fail_all(
                    AppServerTerminatedError(self._process_exit_message(returncode))
                )

    async def _read_stderr(self) -> None:
        process = self._process
        assert process is not None and process.stderr is not None

        while True:
            raw_line = await process.stderr.readline()
            if not raw_line:
                break
            self._stderr_tail.append(raw_line.decode("utf-8", "replace").rstrip())

    def _route_message(self, message: JsonObject) -> None:
        if (
            "id" in message
            and ("result" in message or "error" in message)
            and "method" not in message
        ):
            request_id = message["id"]
            if not isinstance(request_id, (int, str)):
                self._fail_all(AppServerProtocolError("Invalid app-server response ID"))
                return
            pending = self._pending.get(request_id)
            if pending is None or pending.future.done():
                return

            if "error" in message:
                error = message["error"]
                if not isinstance(error, dict):
                    self._fail_all(
                        AppServerProtocolError("Invalid app-server error response")
                    )
                    return
                pending.future.set_exception(
                    AppServerRpcError(
                        pending.method,
                        error.get("code")
                        if isinstance(error.get("code"), int)
                        else None,
                        str(error.get("message", "Unknown JSON-RPC error")),
                        error.get("data"),
                    )
                )
            else:
                pending.future.set_result(message.get("result"))
            return

        method = message.get("method")
        if not isinstance(method, str):
            self._fail_all(
                AppServerProtocolError(f"Unrecognized app-server message: {message!r}")
            )
            return

        params = message.get("params", {})
        if not isinstance(params, dict):
            self._fail_all(AppServerProtocolError("Invalid app-server message params"))
            return

        if "id" in message:
            if not isinstance(message["id"], (int, str)):
                self._fail_all(AppServerProtocolError("Invalid app-server request ID"))
                return
            self._events.put_nowait(
                ServerRequest(
                    request_id=message["id"],
                    method=method,
                    params=params,
                )
            )
        else:
            self._events.put_nowait(ServerNotification(method=method, params=params))

    def _fail_pending(self, exc: Exception) -> None:
        for pending in tuple(self._pending.values()):
            if not pending.future.done():
                pending.future.set_exception(exc)

    def _fail_all(self, exc: Exception) -> None:
        if self._terminal_error is None:
            self._terminal_error = exc
            self._events.put_nowait(exc)
        self._fail_pending(exc)

    def _process_exit_message(self, returncode: int | None) -> str:
        detail = f"codex app-server exited with code {returncode}"
        if self._stderr_tail:
            detail += f". stderr tail: {self._stderr_tail[-1]}"
        return detail
