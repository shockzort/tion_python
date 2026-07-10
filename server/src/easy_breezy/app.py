"""Фабрика FastAPI-приложения и жизненный цикл подсистем."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from easy_breezy import __version__
from easy_breezy.api.rest import system
from easy_breezy.config import Settings
from easy_breezy.logging import setup_logging

log = structlog.get_logger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Создаёт приложение; подсистемы подключаются в lifespan по мере фаз."""
    app_settings = settings if settings is not None else Settings()
    setup_logging(app_settings.log_level, app_settings.log_dir)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.started_at = time.monotonic()
        log.info("service_started", version=__version__)
        yield
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
    return app
