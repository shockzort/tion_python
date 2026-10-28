"""Приборы Xiaomi: список из кэша и команды (docs/xiaomi.md).

Список читается из памяти сервиса (сеть в запросном пути не трогается);
команда и действие синхронные — ответ несёт состояние, подтверждённое
прибором. Настройки (экран, ночной режим, сушка…) — поля той же команды.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from easy_breezy.api.deps import ContainerDep, require_user
from easy_breezy.api.schemas import ApplianceAction, ApplianceCommand
from easy_breezy.integrations.xiaomi.service import (
    ApplianceError,
    ApplianceNotFoundError,
)
from easy_breezy.storage.models import CommandSource

router = APIRouter(
    prefix="/api", tags=["appliances"], dependencies=[Depends(require_user)]
)


class ApplianceView(BaseModel):
    id: str
    name: str
    model: str
    online: bool
    state: dict[str, Any] | None
    state_at: float | None
    error: str | None


@router.get("/appliances")
async def list_appliances(container: ContainerDep) -> list[ApplianceView]:
    return [
        ApplianceView(**snapshot.to_dict()) for snapshot in container.appliances.list()
    ]


@router.post("/appliances/{appliance_id}/command")
async def command_appliance(
    appliance_id: str, body: ApplianceCommand, container: ContainerDep
) -> ApplianceView:
    try:
        snapshot = await container.appliances.command(
            appliance_id, body.to_delta(), source=CommandSource.UI
        )
    except ApplianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplianceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ApplianceView(**snapshot.to_dict())


@router.post("/appliances/{appliance_id}/action")
async def action_appliance(
    appliance_id: str, body: ApplianceAction, container: ContainerDep
) -> ApplianceView:
    try:
        snapshot = await container.appliances.action(
            appliance_id, body.action, source=CommandSource.UI
        )
    except ApplianceNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ApplianceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return ApplianceView(**snapshot.to_dict())
