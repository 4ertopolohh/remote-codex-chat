"""Minimal local FastAPI host for CodexBridge."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from chat_protocol import (
    AgentStatus,
    AssistantDelta,
    Capabilities,
    ChatError,
    ClientMessage,
    ConversationList,
    ConversationSelected,
    ListCapabilities,
    ListConversations,
    NewConversation,
    Ready,
    SelectConversation,
    ServerEvent,
    SteerAccepted,
    SteerTurn,
    StopTurn,
    SubmitPrompt,
    TurnFinished,
    TurnStarted,
)
from codex_bridge import (
    AgentMessageDelta,
    ApprovalDeclined,
    BridgeError,
    CodexBridge,
    ModelCapability,
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
    if isinstance(message, (SubmitPrompt, SteerTurn)) and not message.text.strip():
        raise ValueError("Empty prompt")
    return message


def create_app(
    bridge_factory: Callable[[], CodexBridge] = CodexBridge,
    *,
    project: Path | None = None,
    database: Path | None = None,
    experimental_features: bool | None = None,
) -> FastAPI:
    experimental = (
        os.environ.get("RC_EXPERIMENTAL_FEATURES") == "1"
        if experimental_features is None
        else experimental_features
    )
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
        bridge = (
            CodexBridge(experimental_features=experimental)
            if bridge_factory is CodexBridge
            else bridge_factory()
        )
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
        stopping = False

        async def discover_models() -> tuple[ModelCapability, ...]:
            try:
                return await bridge.list_models()
            except BridgeError:
                return ()

        async def send_capabilities() -> None:
            models = await discover_models()
            modes = ()
            if experimental:
                try:
                    modes = await bridge.list_collaboration_modes()
                except BridgeError:
                    pass
            await send_event(
                ws,
                Capabilities(
                    models=[asdict(model) for model in models],
                    collaboration_modes=[asdict(mode) for mode in modes],
                ),
            )

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
                    if isinstance(message, ListCapabilities):
                        await send_capabilities()
                        continue
                    if isinstance(message, (StopTurn, SteerTurn)):
                        await send_event(ws, ChatError(code="no_active_turn"))
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
                    models = await discover_models()
                    if message.model_id:
                        selected_model = next(
                            (item for item in models if item.id == message.model_id),
                            None,
                        )
                    else:
                        selected_model = next(
                            (item for item in models if item.is_default),
                            models[0] if models else None,
                        )
                    if message.model_id and selected_model is None:
                        await send_event(ws, ChatError(code="model_unavailable"))
                        await send_capabilities()
                        continue
                    if message.reasoning_effort and (
                        selected_model is None
                        or message.reasoning_effort
                        not in selected_model.reasoning_efforts
                    ):
                        await send_event(ws, ChatError(code="reasoning_unavailable"))
                        await send_capabilities()
                        continue
                    modes = ()
                    if message.collaboration_mode:
                        if experimental:
                            try:
                                modes = await bridge.list_collaboration_modes()
                            except BridgeError:
                                pass
                        if selected_model is None or not any(
                            mode.mode == message.collaboration_mode for mode in modes
                        ):
                            await send_event(
                                ws, ChatError(code="collaboration_unavailable")
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
                        conversation.thread_id,
                        message.text,
                        model=selected_model.model if selected_model else None,
                        effort=message.reasoning_effort
                        or (
                            selected_model.default_reasoning_effort
                            if selected_model
                            else None
                        ),
                        collaboration_mode=message.collaboration_mode,
                    )
                    stopping = False
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
                        if receive_task in done:
                            try:
                                active_message = parse_client_message(
                                    receive_task.result()
                                )
                            except WebSocketDisconnect:
                                raise
                            except (ValidationError, ValueError, KeyError, TypeError):
                                await send_event(ws, ChatError(code="invalid_message"))
                            else:
                                if turn_id is None and isinstance(
                                    active_message, (StopTurn, SteerTurn)
                                ):
                                    await send_event(
                                        ws, ChatError(code="no_active_turn")
                                    )
                                elif isinstance(active_message, ListCapabilities):
                                    await send_capabilities()
                                elif isinstance(active_message, StopTurn):
                                    if not stopping:
                                        await bridge.interrupt_turn(
                                            conversation.thread_id, turn_id
                                        )
                                        stopping = True
                                        await send_event(
                                            ws, AgentStatus(status="stopping")
                                        )
                                elif isinstance(active_message, SteerTurn):
                                    if stopping:
                                        await send_event(
                                            ws, ChatError(code="no_active_turn")
                                        )
                                    else:
                                        try:
                                            await bridge.steer_turn(
                                                conversation.thread_id,
                                                turn_id,
                                                active_message.text,
                                            )
                                        except OperationFailed:
                                            await send_event(
                                                ws, ChatError(code="steer_failed")
                                            )
                                        else:
                                            await send_event(
                                                ws,
                                                SteerAccepted(text=active_message.text),
                                            )
                                else:
                                    await send_event(
                                        ws, ChatError(code="turn_in_progress")
                                    )
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
