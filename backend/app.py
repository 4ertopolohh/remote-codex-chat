"""Minimal local FastAPI host for CodexBridge."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from chat_protocol import (
    AgentStatus,
    AssistantDelta,
    ChatError,
    ClientMessage,
    ConversationList,
    ConversationSelected,
    ListConversations,
    NewConversation,
    Ready,
    SelectConversation,
    ServerEvent,
    SubmitPrompt,
    TurnFinished,
    TurnStarted,
)
from codex_bridge import (
    AgentMessageDelta,
    ApprovalDeclined,
    BridgeError,
    CodexBridge,
    OperationFailed,
    ThreadStatusChanged,
    TurnCompleted,
)
from conversation_store import ConversationStore

_client_message_adapter = TypeAdapter(ClientMessage)


async def send_event(ws: WebSocket, event: ServerEvent) -> None:
    await ws.send_json(event.model_dump())


def parse_client_message(raw: object) -> ClientMessage:
    message = _client_message_adapter.validate_python(raw)
    if isinstance(message, SubmitPrompt) and not message.text.strip():
        raise ValueError("Empty prompt")
    return message


def create_app(
    bridge_factory: Callable[[], CodexBridge] = CodexBridge,
    *,
    project: Path | None = None,
    database: Path | None = None,
) -> FastAPI:
    configured_project = (
        project
        or Path(os.environ.get("RC_PROJECT_PATH", Path(__file__).resolve().parents[1]))
    ).resolve()
    database_path = database or Path(
        os.environ.get(
            "RC_DATABASE_PATH",
            Path(__file__).resolve().parent / "data" / "conversations.sqlite3",
        )
    )
    store = ConversationStore(database_path)
    project_id = "default"
    chat_active = False

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        store.initialize()
        bridge = bridge_factory()
        app.state.bridge = bridge
        await bridge.start()
        try:
            yield
        finally:
            await bridge.close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> JSONResponse:
        if app.state.bridge.ready:
            return JSONResponse({"status": "ready"})
        return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.websocket("/ws/chat")
    async def chat(ws: WebSocket) -> None:
        nonlocal chat_active
        if chat_active:
            await ws.close(code=1008, reason="Chat is already in use")
            return
        chat_active = True
        await ws.accept()
        bridge = app.state.bridge
        conversation = None
        turn_id: str | None = None
        try:
            if not bridge.ready:
                await send_event(ws, ChatError(code="codex_unavailable"))
                await ws.close(code=1011)
                return
            await send_event(ws, Ready())
            while True:
                try:
                    raw = await ws.receive_json()
                    message = parse_client_message(raw)
                except (ValidationError, ValueError, KeyError, TypeError):
                    await send_event(ws, ChatError(code="invalid_message"))
                    continue
                try:
                    if isinstance(message, ListConversations):
                        await send_event(
                            ws,
                            ConversationList(
                                conversations=[
                                    item.public() for item in store.list(project_id)
                                ]
                            ),
                        )
                        continue
                    if isinstance(message, NewConversation):
                        thread_id = await bridge.start_thread(configured_project)
                        conversation = store.create(project_id, thread_id)
                        await send_event(
                            ws,
                            ConversationSelected(
                                conversation=conversation.public(), messages=[]
                            ),
                        )
                        continue
                    if isinstance(message, SelectConversation):
                        conversation = None
                        selected = store.get(message.id, project_id)
                        if selected is None:
                            await send_event(
                                ws, ChatError(code="conversation_not_found")
                            )
                            continue
                        try:
                            resumed_id = await bridge.resume_thread(selected.thread_id)
                            if resumed_id != selected.thread_id:
                                raise ValueError("Resumed a different Codex thread")
                            history = await bridge.read_messages(selected.thread_id)
                        except (OperationFailed, ValueError):
                            await send_event(ws, ChatError(code="thread_unavailable"))
                            continue
                        conversation = selected
                        await send_event(
                            ws,
                            ConversationSelected(
                                conversation=selected.public(), messages=history
                            ),
                        )
                        continue
                    if conversation is None:
                        thread_id = await bridge.start_thread(configured_project)
                        conversation = store.create(project_id, thread_id)
                        await send_event(
                            ws,
                            ConversationSelected(
                                conversation=conversation.public(), messages=[]
                            ),
                        )
                    turn_id = await bridge.start_turn(
                        conversation.thread_id, message.text
                    )
                    await send_event(ws, TurnStarted())
                    conversation = store.record_prompt(conversation, message.text)
                    while turn_id is not None:
                        receive_task = asyncio.create_task(ws.receive_json())
                        event_task = asyncio.create_task(bridge.next_event())
                        done, pending = await asyncio.wait(
                            {receive_task, event_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for task in pending:
                            task.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        if receive_task in done:
                            try:
                                parse_client_message(receive_task.result())
                            except WebSocketDisconnect:
                                raise
                            except (ValidationError, ValueError, KeyError, TypeError):
                                await send_event(ws, ChatError(code="invalid_message"))
                            else:
                                await send_event(ws, ChatError(code="turn_in_progress"))
                        if event_task in done:
                            event = event_task.result()
                            if isinstance(event, AgentMessageDelta) and (
                                event.thread_id,
                                event.turn_id,
                            ) == (conversation.thread_id, turn_id):
                                await send_event(ws, AssistantDelta(text=event.text))
                            elif (
                                isinstance(event, ThreadStatusChanged)
                                and event.thread_id == conversation.thread_id
                            ):
                                await send_event(ws, AgentStatus(status=event.status))
                            elif (
                                isinstance(event, ApprovalDeclined)
                                and event.thread_id == conversation.thread_id
                            ):
                                await send_event(
                                    ws, AgentStatus(status="approval_declined")
                                )
                            elif isinstance(event, TurnCompleted) and (
                                event.thread_id,
                                event.turn_id,
                            ) == (conversation.thread_id, turn_id):
                                status = (
                                    event.status
                                    if event.status
                                    in {"completed", "failed", "interrupted"}
                                    else "failed"
                                )
                                await send_event(ws, TurnFinished(status=status))
                                await send_event(
                                    ws,
                                    ConversationList(
                                        conversations=[
                                            item.public()
                                            for item in store.list(project_id)
                                        ]
                                    ),
                                )
                                turn_id = None
                except BridgeError:
                    await send_event(ws, ChatError(code="codex_failure"))
                    turn_id = None
        except WebSocketDisconnect:
            pass
        finally:
            if conversation is not None and turn_id is not None:
                try:
                    await bridge.interrupt_turn(conversation.thread_id, turn_id)
                except BridgeError:
                    pass
            chat_active = False

    return app


app = create_app()
