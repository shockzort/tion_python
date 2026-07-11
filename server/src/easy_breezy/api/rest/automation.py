"""Автоматизация: CRUD сценариев и расписаний, запуск сценария (FR-20/21/24).

CRUD публикует ``automation.changed`` — планировщик пересчитывает ближайшее
срабатывание, UI инвалидирует кэш. Ручной запуск сценария — приоритет 0
(ставит manual-hold, как любая ручная команда, FR-23).
"""

from __future__ import annotations

import asyncio
import uuid as uuid_module
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError

from easy_breezy.api.deps import ContainerDep, require_user
from easy_breezy.api.rest.devices import wait_outcome
from easy_breezy.api.schemas import CommandBody, CommandResult, GroupCommandResult
from easy_breezy.automation.scenarios import ScenarioNotFoundError
from easy_breezy.automation.scheduler import validate_cron
from easy_breezy.container import AppContainer
from easy_breezy.core.events import TOPIC_AUTOMATION_CHANGED
from easy_breezy.storage.models import CommandSource, Scenario, Schedule
from easy_breezy.storage.repos import (
    DeviceRepo,
    GroupRepo,
    ScenarioRepo,
    ScheduleRepo,
)

router = APIRouter(
    prefix="/api", tags=["automation"], dependencies=[Depends(require_user)]
)

_MANUAL_PRIORITY = 0


class ScenarioAction(BaseModel):
    """Действие сценария: цель + дельта; хранится в JSON-поле actions."""

    target_type: Literal["device", "group"]
    target_id: str | int
    delta: CommandBody

    @model_validator(mode="after")
    def _check_target_id(self) -> ScenarioAction:
        if self.target_type == "group" and not isinstance(self.target_id, int):
            raise ValueError("target_id группы — целое число")
        if self.target_type == "device" and not isinstance(self.target_id, str):
            raise ValueError("target_id устройства — uuid-строка")
        return self

    def to_stored(self) -> dict[str, Any]:
        return {
            "target_type": self.target_type,
            "target_id": self.target_id,
            "delta": self.delta.to_delta().to_payload(),
        }


class ScenarioBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    actions: list[ScenarioAction] = Field(min_length=1)


class ScenarioView(BaseModel):
    id: int
    name: str
    actions: list[dict[str, Any]]

    @classmethod
    def from_record(cls, record: Scenario) -> ScenarioView:
        return cls(id=record.id, name=record.name, actions=record.actions)


class ScheduleBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    cron: str = Field(min_length=9, max_length=100)
    scenario_id: int | None = None
    actions: list[ScenarioAction] | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _check(self) -> ScheduleBody:
        if not validate_cron(self.cron):
            raise ValueError("cron не разбирается (нужно 5 полей)")
        if (self.scenario_id is None) == (self.actions is None):
            raise ValueError("задайте либо scenario_id, либо actions (ровно одно)")
        return self

    def stored_actions(self) -> list[dict[str, Any]] | None:
        if self.actions is None:
            return None
        return [action.to_stored() for action in self.actions]


class ScheduleView(BaseModel):
    id: int
    name: str
    cron: str
    scenario_id: int | None
    actions: list[dict[str, Any]] | None
    enabled: bool

    @classmethod
    def from_record(cls, record: Schedule) -> ScheduleView:
        return cls(
            id=record.id,
            name=record.name,
            cron=record.cron,
            scenario_id=record.scenario_id,
            actions=record.actions,
            enabled=record.enabled,
        )


def _notify_changed(
    container: AppContainer, kind: str, action: str, item_id: int
) -> None:
    container.events.publish(
        TOPIC_AUTOMATION_CHANGED, {"kind": kind, "action": action, "id": item_id}
    )


async def _validate_targets(
    container: AppContainer, actions: list[ScenarioAction]
) -> None:
    """Цели действий существуют: устройство активно, группа заведена."""
    async with container.db.session() as session:
        devices = DeviceRepo(session)
        groups = GroupRepo(session)
        for action in actions:
            if action.target_type == "device":
                device = await devices.get(str(action.target_id))
                if device is None or device.deleted_at is not None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"устройство {action.target_id} не найдено",
                    )
            else:
                if await groups.get(int(action.target_id)) is None:
                    raise HTTPException(
                        status_code=404, detail=f"группа {action.target_id} не найдена"
                    )


# --- сценарии --------------------------------------------------------------


@router.get("/scenarios")
async def list_scenarios(container: ContainerDep) -> list[ScenarioView]:
    async with container.db.session() as session:
        scenarios = await ScenarioRepo(session).list_all()
    return [ScenarioView.from_record(record) for record in scenarios]


@router.post("/scenarios", status_code=201)
async def add_scenario(body: ScenarioBody, container: ContainerDep) -> ScenarioView:
    await _validate_targets(container, body.actions)
    try:
        async with container.db.session() as session:
            record = await ScenarioRepo(session).create(
                name=body.name,
                actions=[action.to_stored() for action in body.actions],
            )
            view = ScenarioView.from_record(record)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="сценарий с таким именем уже есть"
        ) from exc
    _notify_changed(container, "scenario", "created", view.id)
    return view


@router.put("/scenarios/{scenario_id}")
async def update_scenario(
    scenario_id: int, body: ScenarioBody, container: ContainerDep
) -> ScenarioView:
    await _validate_targets(container, body.actions)
    try:
        async with container.db.session() as session:
            record = await ScenarioRepo(session).get(scenario_id)
            if record is None:
                raise HTTPException(status_code=404, detail="сценарий не найден")
            record.name = body.name
            record.actions = [action.to_stored() for action in body.actions]
            view = ScenarioView.from_record(record)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="сценарий с таким именем уже есть"
        ) from exc
    _notify_changed(container, "scenario", "updated", scenario_id)
    return view


@router.delete("/scenarios/{scenario_id}", status_code=204)
async def remove_scenario(scenario_id: int, container: ContainerDep) -> None:
    """Удаляет сценарий; его расписания уходят каскадом (FK)."""
    async with container.db.session() as session:
        repo = ScenarioRepo(session)
        record = await repo.get(scenario_id)
        if record is None:
            raise HTTPException(status_code=404, detail="сценарий не найден")
        await repo.delete(record)
    _notify_changed(container, "scenario", "deleted", scenario_id)


@router.post("/scenarios/{scenario_id}/run")
async def run_scenario(
    scenario_id: int, response: Response, container: ContainerDep
) -> list[GroupCommandResult]:
    """Запуск кнопкой: ручной приоритет, итоги ждём как у групповой команды."""
    prefix = f"scenario:{scenario_id}:{uuid_module.uuid4().hex}"
    try:
        submissions = await container.scenarios.run(
            scenario_id,
            source=CommandSource.SCENARIO,
            idempotency_prefix=prefix,
            priority=_MANUAL_PRIORITY,
        )
    except ScenarioNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    results: list[GroupCommandResult] = []
    waiters: list[tuple[str, asyncio.Task[CommandResult]]] = []
    for submission in submissions:
        if submission.ticket is None:
            results.append(
                GroupCommandResult(
                    device_uuid=submission.device_uuid, rejected=submission.rejected
                )
            )
            continue
        waiters.append(
            (
                submission.device_uuid,
                asyncio.create_task(wait_outcome(container, submission.ticket)),
            )
        )
    for device_uuid, waiter in waiters:
        results.append(GroupCommandResult(device_uuid=device_uuid, result=await waiter))
    if any(
        entry.result is not None and entry.result.status == "pending"
        for entry in results
    ):
        response.status_code = 202
    return results


# --- расписания ------------------------------------------------------------


@router.get("/schedules")
async def list_schedules(container: ContainerDep) -> list[ScheduleView]:
    async with container.db.session() as session:
        schedules = await ScheduleRepo(session).list_all()
    return [ScheduleView.from_record(record) for record in schedules]


@router.post("/schedules", status_code=201)
async def add_schedule(body: ScheduleBody, container: ContainerDep) -> ScheduleView:
    if body.actions is not None:
        await _validate_targets(container, body.actions)
    async with container.db.session() as session:
        if (
            body.scenario_id is not None
            and await ScenarioRepo(session).get(body.scenario_id) is None
        ):
            raise HTTPException(status_code=404, detail="сценарий не найден")
        record = await ScheduleRepo(session).create(
            name=body.name,
            cron=body.cron,
            scenario_id=body.scenario_id,
            actions=body.stored_actions(),
            enabled=body.enabled,
        )
        view = ScheduleView.from_record(record)
    _notify_changed(container, "schedule", "created", view.id)
    return view


@router.put("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: int, body: ScheduleBody, container: ContainerDep
) -> ScheduleView:
    if body.actions is not None:
        await _validate_targets(container, body.actions)
    async with container.db.session() as session:
        repo = ScheduleRepo(session)
        record = await repo.get(schedule_id)
        if record is None:
            raise HTTPException(status_code=404, detail="расписание не найдено")
        if (
            body.scenario_id is not None
            and await ScenarioRepo(session).get(body.scenario_id) is None
        ):
            raise HTTPException(status_code=404, detail="сценарий не найден")
        record.name = body.name
        record.cron = body.cron
        record.scenario_id = body.scenario_id
        record.actions = body.stored_actions()
        record.enabled = body.enabled
        view = ScheduleView.from_record(record)
    _notify_changed(container, "schedule", "updated", schedule_id)
    return view


@router.delete("/schedules/{schedule_id}", status_code=204)
async def remove_schedule(schedule_id: int, container: ContainerDep) -> None:
    async with container.db.session() as session:
        repo = ScheduleRepo(session)
        record = await repo.get(schedule_id)
        if record is None:
            raise HTTPException(status_code=404, detail="расписание не найдено")
        await repo.delete(record)
    _notify_changed(container, "schedule", "deleted", schedule_id)
