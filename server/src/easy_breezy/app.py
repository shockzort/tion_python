"""Фабрика FastAPI-приложения и жизненный цикл подсистем."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response
from starlette.types import Scope

from easy_breezy import __version__
from easy_breezy.api import ws
from easy_breezy.api.rest import auth, commands, devices, groups, pairing, system
from easy_breezy.config import Settings
from easy_breezy.container import build_container
from easy_breezy.integrations.yandex import oauth as yandex_oauth
from easy_breezy.integrations.yandex import router as yandex_router
from easy_breezy.logging import setup_logging

log = structlog.get_logger(__name__)


_RESERVED_PREFIXES = ("api", "v1.0", "oauth")


def _is_reserved(path: str) -> bool:
    return any(
        path == prefix or path.startswith(prefix + "/") for prefix in _RESERVED_PREFIXES
    )


class SpaStaticFiles(StaticFiles):
    """Статика PWA: неизвестные пути отдают index.html (client-side роутер).

    Зарезервированные префиксы (/api, /v1.0, /oauth) в fallback не попадают:
    несуществующий API-путь обязан отвечать честным 404, а не HTML со статусом
    200 — иначе ошибки конфигурации (например, лишний /v1.0 в Endpoint URL
    навыка) маскируются до самых дальних стадий.
    """

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not _is_reserved(path):
                return await super().get_response("index.html", scope)
            raise


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
    app.include_router(yandex_oauth.router)
    app.include_router(yandex_router.router)

    # статика — после роутеров: /api, /oauth и /v1.0 матчатся первыми
    if (app_settings.ui_dist / "index.html").exists():
        app.mount(
            "/", SpaStaticFiles(directory=app_settings.ui_dist, html=True), name="ui"
        )
        log.info("ui_static_mounted", path=str(app_settings.ui_dist))
    else:
        log.info("ui_static_absent", path=str(app_settings.ui_dist))
    return app
