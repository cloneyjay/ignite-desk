"""FastAPI application.

Run with:
    python -m backend.ignite.api

The app binds 127.0.0.1 only. The browser talks to it directly; in development
Vite proxies /api here.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.ignite.api.errors import install_handlers
from backend.ignite.api.routes import (
    account,
    agent,
    analyses,
    drafts,
    events,
    market,
    news,
    system,
    trades,
)
from backend.ignite.config import Settings, load_settings
from backend.ignite.services.runtime import Runtime

log = logging.getLogger("ignite.api")

LOCAL_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
]


def create_app(
    settings: Settings | None = None, runtime: Runtime | None = None
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        rt = runtime or Runtime(settings or load_settings())
        rt.events.bind(asyncio.get_running_loop())
        app.state.runtime = rt
        threading.Thread(target=rt.seed_symbols, daemon=True).start()
        log.info("ignite api ready (db=%s)", rt.settings.db_path)
        try:
            yield
        finally:
            rt.shutdown()

    app = FastAPI(
        title="Ignite Desk API",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=LOCAL_ORIGINS,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_handlers(app)

    for module in (
        system,
        account,
        market,
        analyses,
        drafts,
        trades,
        news,
        events,
        agent,
    ):
        app.include_router(module.router)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, Any]:
        return {
            "name": "Ignite Desk API",
            "docs": "/api/docs",
            "health": "/api/health",
        }

    return app


app = create_app()


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    bind = load_settings()
    uvicorn.run(
        "backend.ignite.api.app:create_app",
        factory=True,
        host=bind.bind_host,
        port=bind.bind_port,
    )
