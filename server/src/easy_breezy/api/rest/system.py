"""Системные эндпоинты: здоровье (открытое) и статистика (под auth)."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from easy_breezy import __version__
from easy_breezy.api.deps import ContainerDep, UserDep
from easy_breezy.ble.supervisor import ConnectionState

router = APIRouter(prefix="/api/system", tags=["system"])


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float


class StatsResponse(BaseModel):
    version: str
    uptime_seconds: float
    devices_total: int
    devices_online: int
    ws_clients: int


def _uptime(request: Request) -> float:
    started_at: float = getattr(request.app.state, "started_at", time.monotonic())
    return round(time.monotonic() - started_at, 3)


@router.get("/health")
async def health(request: Request) -> HealthResponse:
    """Проверка живости; используется watchdog'ом, CI и мониторингом."""
    return HealthResponse(
        status="ok", version=__version__, uptime_seconds=_uptime(request)
    )


@router.get("/stats")
async def stats(
    request: Request, container: ContainerDep, _user: UserDep
) -> StatsResponse:
    connections = container.registry.connections()
    return StatsResponse(
        version=__version__,
        uptime_seconds=_uptime(request),
        devices_total=len(connections),
        devices_online=sum(
            1 for state in connections.values() if state is ConnectionState.ONLINE
        ),
        ws_clients=len(container.ws_connections),
    )
