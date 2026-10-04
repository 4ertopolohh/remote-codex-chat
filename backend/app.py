"""Minimal local FastAPI host for CodexBridge."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from codex_bridge import CodexBridge


def create_app(bridge_factory: Callable[[], CodexBridge] = CodexBridge) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
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

    return app


app = create_app()
