"""Фабрика FastAPI-приложения и жизненный цикл подсистем."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from easy_breezy import __version__
from easy_breezy.api import ws
from easy_breezy.api.rest import auth, commands, devices, groups, pairing, system
from easy_breezy.config import Settings
from easy_breezy.container import build_container
from easy_breezy.logging import setup_logging

log = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение; подсистемы собираются контейнером в lifespan."""
    app_settings = settings if settings is not None else Settings()
    setup_logging(app_settings.log_level, app_settings.log_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.monotonic()
        container = build_container(app_settings)
        app.state.container = container
        await container.startup()
        log.info(
            "service_started",
            version=__version__,
            fake_devices=app_settings.fake_devices,
        )
        yield
        await container.shutdown()
        log.info("service_stopped")

    app = FastAPI(
        title="Easy Breezy",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.state.settings = app_settings
    app.include_router(system.router)
    app.include_router(auth.router)
    app.include_router(devices.router)
    app.include_router(groups.router)
    app.include_router(commands.router)
    app.include_router(pairing.router)
    app.include_router(ws.router)
    return app
