"""Системные эндпоинты: здоровье и диагностика."""

from __future__ import annotations

import time

from fastapi import APIRouter, Request
from pydantic import BaseModel

from easy_breezy import __version__

router = APIRouter(prefix="/api/system", tags=["system"])


class HealthResponse(BaseModel):
    status: str
    version: str
    uptime_seconds: float


@router.get("/health")
async def health(request: Request) -> HealthResponse:
    """Проверка живости; используется watchdog'ом, CI и мониторингом."""
    started_at: float = getattr(request.app.state, "started_at", time.monotonic())
    return HealthResponse(
        status="ok",
        version=__version__,
        uptime_seconds=round(time.monotonic() - started_at, 3),
    )
