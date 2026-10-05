"""Minimal local FastAPI host for CodexBridge."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import TypeAdapter, ValidationError

from auth import SESSION_AGE, AuthService, AuthSettings
from chat_protocol import (
    AgentStatus,
    AnswerApproval,
    AnswerUserInput,
    AssistantDelta,
    Capabilities,
    ChatError,
    ClientMessage,
    ConversationList,
    ConversationSelected,
    ListCapabilities,
    ListConversations,
    ListProjects,
    NewConversation,
    PendingRequest,
    ProjectList,
    ProjectSelected,
    ReadUsage,
    Ready,
    RequestOutcome,
    SelectConversation,
    SelectProject,
    ServerEvent,
    SteerAccepted,
    SteerTurn,
    StopTurn,
    SubmitPrompt,
    TurnFinished,
    TurnStarted,
    Usage,
    UsageUpdate,
)
from codex_bridge import (
    AgentMessageDelta,
    BridgeError,
    CodexBridge,
    CollaborationCapability,
    ModelCapability,
    OperationFailed,
    RequestFinished,
    RequestPending,
    ThreadStatusChanged,
    TurnCompleted,
)
from conversation_store import ConversationStore
from projects import Project, ProjectAllowlist, ProjectUnavailable

_client_message_adapter = TypeAdapter(ClientMessage)


async def send_event(ws: WebSocket, event: ServerEvent) -> None:
    await ws.send_json(event.model_dump())


def parse_client_message(raw: object) -> ClientMessage:
    message = _client_message_adapter.validate_python(raw)
    if isinstance(message, (SubmitPrompt, SteerTurn)) and not message.text.strip():
        raise ValueError("Empty prompt")
    return message


def observe_background_task(task: asyncio.Task[object]) -> None:
    if not task.cancelled():
        task.exception()


def create_app(
    bridge_factory: Callable[[], CodexBridge] = CodexBridge,
    *,
    project: Path | None = None,
    database: Path | None = None,
    experimental_features: bool | None = None,
    auth_settings: AuthSettings | None = None,
) -> FastAPI:
    experimental = (
        os.environ.get("RC_EXPERIMENTAL_FEATURES") == "1"
        if experimental_features is None
        else experimental_features
    )
    if project is not None:
        projects = ProjectAllowlist([Project("default", "Default", project.resolve())])
    elif os.environ.get("RC_PROJECTS") is not None:
        projects = ProjectAllowlist.from_json(os.environ["RC_PROJECTS"])
    else:
        fallback = Path(
            os.environ.get("RC_PROJECT_PATH", Path(__file__).resolve().parents[1])
        )
        projects = ProjectAllowlist([Project("default", "Default", fallback)])
    database_path = database or Path(
        os.environ.get(
            "RC_DATABASE_PATH",
            Path(__file__).resolve().parent / "data" / "conversations.sqlite3",
        )
    )
    configured_dist = os.environ.get("RC_FRONTEND_DIST")
    if configured_dist == "":
        raise ValueError("RC_FRONTEND_DIST must be a built frontend directory")
    frontend_dist = Path(configured_dist) if configured_dist else Path(__file__).resolve().parents[1] / "frontend" / "dist"
    store = ConversationStore(database_path)
    chat_active = False
    draining_tasks: set[asyncio.Task[object]] = set()

    async def drain_interrupted_turn(bridge: CodexBridge, thread_id: str, active_turn_id: str) -> None:
        nonlocal chat_active
        try:
            while True:
                event = await bridge.next_event()
                if isinstance(event, TurnCompleted) and (
                    event.thread_id, event.turn_id
                ) == (thread_id, active_turn_id):
                    return
        except BridgeError:
            # A terminated app-server cannot emit the completion event.
            pass
        finally:
            chat_active = False

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        auth = AuthService(auth_settings or AuthSettings.from_env())
        if auth.settings.remote and not (frontend_dist / "index.html").is_file():
            raise ValueError("Remote mode requires a built frontend at RC_FRONTEND_DIST")
        auth.initialize()
        app.state.auth = auth
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
            for task in draining_tasks:
                task.cancel()
            if draining_tasks:
                await asyncio.gather(*draining_tasks, return_exceptions=True)
            await bridge.close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    def same_origin(request: Request) -> bool:
        return request.headers.get("origin") == request.app.state.auth.settings.origin

    def require_session(request: Request) -> tuple[str, float]:
        auth: AuthService = request.app.state.auth
        session = auth.session(request.cookies.get(auth.settings.cookie_name))
        if session is None:
            raise HTTPException(status_code=401, detail="Unauthorized")
        return session

    @app.post("/auth/login")
    async def login(request: Request) -> JSONResponse:
        auth: AuthService = request.app.state.auth
        if not same_origin(request) or request.headers.get("content-type", "").split(";", 1)[0].lower() != "application/json":
            raise HTTPException(status_code=403, detail="Forbidden")
        body = await request.body()
        if len(body) > 4096:
            raise HTTPException(status_code=413, detail="Request too large")
        try:
            payload = await request.json()
        except ValueError:
            payload = None
        password = payload.get("password") if isinstance(payload, dict) else None
        if not isinstance(password, str):
            password = ""
        result = auth.login(password, request.client.host if request.client else "unknown")
        if result is None:
            return JSONResponse({"detail": "Invalid credentials"}, status_code=401, headers={"Cache-Control": "no-store"})
        token, csrf = result
        response = JSONResponse({"csrf": csrf}, headers={"Cache-Control": "no-store"})
        response.set_cookie(auth.settings.cookie_name, token, max_age=SESSION_AGE, httponly=True, secure=auth.settings.remote, samesite="strict", path="/")
        return response

    @app.get("/auth/session")
    async def session(request: Request) -> JSONResponse:
        csrf, _ = require_session(request)
        return JSONResponse({"csrf": csrf}, headers={"Cache-Control": "no-store"})

    @app.post("/auth/logout")
    async def logout(request: Request) -> JSONResponse:
        csrf, _ = require_session(request)
        if not same_origin(request) or request.headers.get("x-csrf-token") != csrf:
            raise HTTPException(status_code=403, detail="Forbidden")
        auth: AuthService = request.app.state.auth
        token = request.cookies[auth.settings.cookie_name]
        sockets = auth.logout(token)
        for socket in sockets:
            try:
                await socket.close(code=4401)
            except RuntimeError:
                pass
        response = JSONResponse({"status": "logged_out"}, headers={"Cache-Control": "no-store"})
        response.delete_cookie(auth.settings.cookie_name, path="/", secure=auth.settings.remote, httponly=True, samesite="strict")
        return response

    @app.get("/ready")
    async def ready(request: Request) -> JSONResponse:
        require_session(request)
        if app.state.bridge.ready:
            return JSONResponse({"status": "ready"})
        return JSONResponse({"status": "unavailable"}, status_code=503)

    @app.websocket("/ws/chat")
    async def chat(ws: WebSocket) -> None:
        nonlocal chat_active
        auth: AuthService = app.state.auth
        token = ws.cookies.get(auth.settings.cookie_name)
        session = auth.session(token)
        if ws.headers.get("origin") != auth.settings.origin or session is None:
            await ws.close(code=4401 if session is None else 1008)
            return
        if chat_active:
            await ws.close(code=1008, reason="Chat is already in use")
            return
        chat_active = True
        await ws.accept()
        assert token is not None
        auth.register_socket(token, ws)
        async def expire_socket() -> None:
            await asyncio.sleep(max(0, session[1] - time.time()))
            try:
                await ws.close(code=4401)
            except RuntimeError:
                pass
        expiry_task = asyncio.create_task(expire_socket())
        bridge = app.state.bridge
        project_id = projects.default_id
        conversation = None
        turn_id: str | None = None
        stopping = False
        visible_requests: set[str] = set()
        receive_task: asyncio.Task[object] | None = None
        event_task: asyncio.Task[object] | None = None
        usage_task: asyncio.Task[None] | None = None
        usage_updates_task: asyncio.Task[None] | None = None
        pending_message: ClientMessage | None = None

        async def discover_models() -> tuple[ModelCapability, ...]:
            try:
                return await bridge.list_models()
            except BridgeError:
                return ()

        async def discover_modes() -> tuple[CollaborationCapability, ...]:
            if not experimental:
                return ()
            try:
                return await bridge.list_collaboration_modes()
            except BridgeError:
                return ()

        async def send_capabilities() -> None:
            models = await discover_models()
            modes = await discover_modes()
            await send_event(
                ws,
                Capabilities(
                    models=[asdict(model) for model in models],
                    collaboration_modes=[asdict(mode) for mode in modes],
                    user_input="supported"
                    if bridge.user_input_supported
                    else "unsupported",
                ),
            )

        async def send_usage() -> None:
            try:
                snapshot = await bridge.read_usage()
                await send_event(ws, Usage(**snapshot))
            except BridgeError:
                await send_event(ws, Usage(status="error"))

        def start_usage_read() -> None:
            nonlocal usage_task
            if usage_task is None or usage_task.done():
                usage_task = asyncio.create_task(send_usage())
                usage_task.add_done_callback(observe_background_task)

        async def relay_usage_updates() -> None:
            while True:
                update = await bridge.next_usage_update()
                await send_event(ws, UsageUpdate(rate_limits=update.rate_limits))

        try:
            if not bridge.ready:
                await send_event(ws, ChatError(code="codex_unavailable"))
                await ws.close(code=1011)
                return
            await send_event(ws, Ready())
            usage_updates_task = asyncio.create_task(relay_usage_updates())
            usage_updates_task.add_done_callback(observe_background_task)
            while True:
                try:
                    if pending_message is not None:
                        message = pending_message
                        pending_message = None
                    else:
                        if receive_task is not None:
                            raw = await receive_task
                            receive_task = None
                        else:
                            raw = await ws.receive_json()
                        message = parse_client_message(raw)
                except (ValidationError, ValueError, KeyError, TypeError):
                    await send_event(ws, ChatError(code="invalid_message"))
                    continue
                try:
                    if isinstance(message, ListProjects):
                        await send_event(
                            ws,
                            ProjectList(
                                projects=projects.public(), selected_id=project_id
                            ),
                        )
                        continue
                    if isinstance(message, SelectProject):
                        if not projects.contains(message.id):
                            await send_event(ws, ChatError(code="project_not_found"))
                            continue
                        project_id = message.id
                        conversation = None
                        await send_event(ws, ProjectSelected(id=project_id))
                        continue
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
                    if isinstance(message, ReadUsage):
                        start_usage_read()
                        continue
                    if isinstance(message, (StopTurn, SteerTurn)):
                        await send_event(ws, ChatError(code="no_active_turn"))
                        continue
                    if isinstance(message, (AnswerApproval, AnswerUserInput)):
                        await send_event(ws, ChatError(code="request_unavailable"))
                        continue
                    if isinstance(message, NewConversation):
                        thread_id = await bridge.start_thread(projects.resolve(project_id))
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
                            trusted_project = projects.resolve(project_id)
                            resumed_id = await bridge.resume_thread(
                                selected.thread_id, trusted_project
                            )
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
                    modes = await discover_modes() if message.collaboration_mode else ()
                    selected_mode = next(
                        (
                            mode
                            for mode in modes
                            if mode.mode == message.collaboration_mode
                        ),
                        None,
                    )
                    if message.collaboration_mode and selected_mode is None:
                        await send_event(
                            ws, ChatError(code="collaboration_unavailable")
                        )
                        continue
                    preset_model = None
                    if message.model_id:
                        selected_model = next(
                            (item for item in models if item.id == message.model_id),
                            None,
                        )
                    else:
                        preset_model = (
                            next(
                                (
                                    item
                                    for item in models
                                    if item.model == selected_mode.model
                                    or item.id == selected_mode.model
                                ),
                                None,
                            )
                            if selected_mode and selected_mode.model
                            else None
                        )
                        selected_model = next(
                            (item for item in models if item.is_default),
                            models[0] if models else None,
                        )
                        if preset_model:
                            selected_model = preset_model
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
                    if message.collaboration_mode and (
                        selected_model is None
                        or (
                            selected_mode is not None
                            and selected_mode.model
                            and not message.model_id
                            and preset_model is None
                        )
                    ):
                        await send_event(
                            ws, ChatError(code="collaboration_unavailable")
                        )
                        continue
                    if conversation is None:
                        thread_id = await bridge.start_thread(projects.resolve(project_id))
                        conversation = store.create(project_id, thread_id)
                        await send_event(
                            ws,
                            ConversationSelected(
                                conversation=conversation.public(), messages=[]
                            ),
                        )
                    if message.request_id and not store.claim_submission(
                        message.request_id, conversation.id
                    ):
                        await send_event(ws, ChatError(code="duplicate_submission"))
                        continue
                    turn_id = await bridge.start_turn(
                        conversation.thread_id,
                        message.text,
                        model=selected_model.model if selected_model else None,
                        effort=message.reasoning_effort
                        or (
                            selected_mode.reasoning_effort
                            if selected_mode
                            and selected_model
                            and selected_mode.reasoning_effort
                            in selected_model.reasoning_efforts
                            else None
                        )
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
                        if receive_task is None:
                            receive_task = asyncio.create_task(ws.receive_json())
                        if event_task is None:
                            event_task = asyncio.create_task(bridge.next_event())
                        done, _ = await asyncio.wait(
                            {receive_task, event_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if event_task in done:
                            completed_event_task = event_task
                            event_task = None
                            event = completed_event_task.result()
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
                            elif isinstance(event, RequestPending):
                                if (event.thread_id, event.turn_id) == (
                                    conversation.thread_id,
                                    turn_id,
                                ):
                                    visible_requests.add(event.id)
                                    await send_event(
                                        ws,
                                        PendingRequest(
                                            id=event.id,
                                            kind=event.kind,
                                            details=event.details,
                                        ),
                                    )
                                else:
                                    await bridge.cancel_request(event.id)
                            elif isinstance(event, RequestFinished):
                                if event.id in visible_requests:
                                    visible_requests.remove(event.id)
                                    await send_event(
                                        ws,
                                        RequestOutcome(
                                            id=event.id, status=event.status
                                        ),
                                    )
                            elif isinstance(event, TurnCompleted) and (
                                event.thread_id,
                                event.turn_id,
                            ) == (conversation.thread_id, turn_id):
                                for pending_id in tuple(visible_requests):
                                    await bridge.cancel_request(pending_id)
                                    await send_event(
                                        ws,
                                        RequestOutcome(
                                            id=pending_id, status="cancelled"
                                        ),
                                    )
                                    visible_requests.remove(pending_id)
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
                            completed_receive_task = receive_task
                            receive_task = None
                            try:
                                active_message = parse_client_message(
                                    completed_receive_task.result()
                                )
                            except WebSocketDisconnect:
                                raise
                            except (ValidationError, ValueError, KeyError, TypeError):
                                await send_event(ws, ChatError(code="invalid_message"))
                            else:
                                if turn_id is None:
                                    pending_message = active_message
                                elif isinstance(active_message, ListCapabilities):
                                    await send_capabilities()
                                elif isinstance(active_message, ReadUsage):
                                    start_usage_read()
                                elif isinstance(
                                    active_message, (AnswerApproval, AnswerUserInput)
                                ):
                                    if active_message.id not in visible_requests:
                                        await send_event(
                                            ws, ChatError(code="request_unavailable")
                                        )
                                    else:
                                        try:
                                            if isinstance(
                                                active_message, AnswerApproval
                                            ):
                                                accepted = await bridge.answer_request(
                                                    active_message.id,
                                                    active_message.decision,
                                                )
                                            else:
                                                accepted = (
                                                    await bridge.answer_user_input(
                                                        active_message.id,
                                                        active_message.answers,
                                                    )
                                                )
                                        except BridgeError:
                                            accepted = False
                                        if not accepted:
                                            await send_event(
                                                ws,
                                                ChatError(code="request_unavailable"),
                                            )
                                elif isinstance(active_message, StopTurn):
                                    if not stopping:
                                        try:
                                            await bridge.interrupt_turn(
                                                conversation.thread_id, turn_id
                                            )
                                        except OperationFailed:
                                            await send_event(
                                                ws, ChatError(code="stop_failed")
                                            )
                                        else:
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
                except ProjectUnavailable:
                    await send_event(ws, ChatError(code="project_unavailable"))
                    turn_id = None
                except BridgeError:
                    await send_event(ws, ChatError(code="codex_failure"))
                    turn_id = None
        except WebSocketDisconnect:
            pass
        finally:
            expiry_task.cancel()
            auth.unregister_socket(token, ws)
            if usage_task is not None and not usage_task.done():
                usage_task.cancel()
            if usage_updates_task is not None and not usage_updates_task.done():
                usage_updates_task.cancel()
            if event_task is not None and event_task.done() and turn_id is not None:
                try:
                    pending_event = event_task.result()
                    if isinstance(pending_event, TurnCompleted) and conversation is not None and (
                        pending_event.thread_id, pending_event.turn_id
                    ) == (conversation.thread_id, turn_id):
                        turn_id = None
                except (asyncio.CancelledError, BridgeError):
                    pass
            tasks = [task for task in (receive_task, event_task) if task is not None]
            for task in tasks:
                task.add_done_callback(observe_background_task)
                if not task.done():
                    task.cancel()
            try:
                await bridge.cancel_pending()
            except BridgeError:
                pass
            if conversation is not None and turn_id is not None:
                try:
                    await bridge.interrupt_turn(conversation.thread_id, turn_id)
                except BridgeError:
                    pass
                task = asyncio.create_task(
                    drain_interrupted_turn(bridge, conversation.thread_id, turn_id)
                )
                draining_tasks.add(task)
                task.add_done_callback(draining_tasks.discard)
                task.add_done_callback(observe_background_task)
            else:
                chat_active = False

    if (frontend_dist / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return app


app = create_app()
