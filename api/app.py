"""FastAPI application factory with lifespan management."""
from __future__ import annotations

import logging
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from tion_btle.domain.device_manager.device_manager import DeviceManager
from tion_btle.domain.device_manager.sqlite_storage import SQLiteDeviceStorage
from tion_btle.operator import Operator
from tion_btle.scenarist import Scenarist

_LOGGER = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan: initialize and shutdown resources.

    Args:
        app: FastAPI application instance.

    Yields:
        None — control returns to FastAPI while the app is running.
    """
    db_path = os.getenv("DB_PATH", "devices.db")

    # Initialize storage and managers
    device_storage = SQLiteDeviceStorage(db_path)
    group_storage = SQLiteDeviceStorage(db_path)
    device_manager = DeviceManager(device_storage, group_storage)
    scenarist = Scenarist(db_path)
    operator = Operator(db_path)

    # Store in app state for dependency injection
    app.state.device_manager = device_manager
    app.state.scenarist = scenarist
    app.state.operator = operator

    _LOGGER.info("Initializing Operator...")
    await operator.initialize()

    _LOGGER.info("Starting device polling...")
    await operator.start_polling(interval=int(os.getenv("POLL_INTERVAL", "60")))

    _LOGGER.info("Starting scenario runner...")
    await operator.run_scenarios()

    _LOGGER.info("Application startup complete")

    yield  # Application is running

    # Graceful shutdown
    _LOGGER.info("Shutting down Operator...")
    await operator.shutdown()
    _LOGGER.info("Operator shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    from api.routes.devices import router as devices_router
    from api.routes.yandex import router as yandex_router

    application = FastAPI(
        title="Tion Breezer Control",
        description="Control Tion breezer devices with Yandex Alice integration",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Register routers
    application.include_router(yandex_router)
    application.include_router(devices_router)

    return application


app = create_app()
