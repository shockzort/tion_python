"""Датчики и триггеры: реестр и CRUD (FR-22/24/26).

MQTT-датчики заводятся вручную (source_key = базовый топик брокера);
MagicAir-датчики появляются сами при опросе облака — здесь их можно
переименовать, привязать к комнате или удалить. Изменение реестра публикует
``device.list_changed`` (MQTT-переподписка + Яндекс-discovery), CRUD
триггеров — ``automation.changed`` (обновление UI).
"""

from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.exc import IntegrityError

from easy_breezy.api.deps import ContainerDep, require_user
from easy_breezy.api.rest.automation import ScenarioAction, _notify_changed
from easy_breezy.container import AppContainer
from easy_breezy.core.events import TOPIC_DEVICE_LIST_CHANGED
from easy_breezy.core.sensors import KIND_MQTT, STALE_AFTER_SECONDS
from easy_breezy.storage.models import Sensor, Trigger
from easy_breezy.storage.repos import (
    RoomRepo,
    ScenarioRepo,
    SensorRepo,
    TriggerRepo,
)

router = APIRouter(
    prefix="/api", tags=["sensors"], dependencies=[Depends(require_user)]
)

_WINDOW_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


class SensorView(BaseModel):
    id: int
    kind: str
    name: str
    source_key: str
    room_id: int | None
    last_values: dict[str, float] | None
    last_seen_at: int | None
    stale: bool

    @classmethod
    def from_record(cls, record: Sensor, *, now: float) -> SensorView:
        return cls(
            id=record.id,
            kind=record.kind,
            name=record.name,
            source_key=record.source_key,
            room_id=record.room_id,
            last_values=record.last_values,
            last_seen_at=record.last_seen_at,
            stale=(
                record.last_seen_at is None
                or now - record.last_seen_at > STALE_AFTER_SECONDS
            ),
        )


class SensorCreate(BaseModel):
    """Ручная регистрация MQTT-датчика (MagicAir приходят из облака сами)."""

    name: str = Field(min_length=1, max_length=100)
    source_key: str = Field(min_length=1, max_length=200)
    room_id: int | None = None


class SensorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    room_id: int | None = None


class TriggerBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sensor_id: int
    metric: Literal["co2", "temperature", "humidity"]
    op: Literal[">", "<"]
    threshold: float
    hysteresis: float = Field(default=0.0, ge=0)
    cooldown_s: int = Field(default=0, ge=0)
    window_start: str | None = Field(default=None, pattern=_WINDOW_PATTERN)
    window_end: str | None = Field(default=None, pattern=_WINDOW_PATTERN)
    enter_scenario_id: int | None = None
    enter_actions: list[ScenarioAction] | None = None
    exit_scenario_id: int | None = None
    exit_actions: list[ScenarioAction] | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _check(self) -> TriggerBody:
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("окно задаётся обеими границами или никак")
        if self.enter_scenario_id is not None and self.enter_actions is not None:
            raise ValueError("enter: либо сценарий, либо действия")
        if self.exit_scenario_id is not None and self.exit_actions is not None:
            raise ValueError("exit: либо сценарий, либо действия")
        has_enter = self.enter_scenario_id is not None or self.enter_actions is not None
        has_exit = self.exit_scenario_id is not None or self.exit_actions is not None
        if not has_enter and not has_exit:
            raise ValueError("задайте действия хотя бы на вход или на выход")
        return self

    def stored_fields(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "sensor_id": self.sensor_id,
            "metric": self.metric,
            "op": self.op,
            "threshold": self.threshold,
            "hysteresis": self.hysteresis,
            "cooldown_s": self.cooldown_s,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "enter_scenario_id": self.enter_scenario_id,
            "enter_actions": (
                [action.to_stored() for action in self.enter_actions]
                if self.enter_actions is not None
                else None
            ),
            "exit_scenario_id": self.exit_scenario_id,
            "exit_actions": (
                [action.to_stored() for action in self.exit_actions]
                if self.exit_actions is not None
                else None
            ),
            "enabled": self.enabled,
        }


class TriggerView(BaseModel):
    id: int
    name: str
    sensor_id: int
    metric: str
    op: str
    threshold: float
    hysteresis: float
    cooldown_s: int
    window_start: str | None
    window_end: str | None
    enter_scenario_id: int | None
    enter_actions: list[dict[str, Any]] | None
    exit_scenario_id: int | None
    exit_actions: list[dict[str, Any]] | None
    enabled: bool
    is_active: bool

    @classmethod
    def from_record(cls, record: Trigger) -> TriggerView:
        return cls(
            id=record.id,
            name=record.name,
            sensor_id=record.sensor_id,
            metric=record.metric,
            op=record.op,
            threshold=record.threshold,
            hysteresis=record.hysteresis,
            cooldown_s=record.cooldown_s,
            window_start=record.window_start,
            window_end=record.window_end,
            enter_scenario_id=record.enter_scenario_id,
            enter_actions=record.enter_actions,
            exit_scenario_id=record.exit_scenario_id,
            exit_actions=record.exit_actions,
            enabled=record.enabled,
            is_active=record.is_active,
        )


async def _check_trigger_refs(container: AppContainer, body: TriggerBody) -> None:
    async with container.db.session() as session:
        if await SensorRepo(session).get(body.sensor_id) is None:
            raise HTTPException(status_code=404, detail="датчик не найден")
        scenarios = ScenarioRepo(session)
        for scenario_id in (body.enter_scenario_id, body.exit_scenario_id):
            if scenario_id is not None and await scenarios.get(scenario_id) is None:
                raise HTTPException(status_code=404, detail="сценарий не найден")


# --- датчики ---------------------------------------------------------------


@router.get("/sensors")
async def list_sensors(container: ContainerDep) -> list[SensorView]:
    now = time.time()
    async with container.db.session() as session:
        sensors = await SensorRepo(session).list_all()
    return [SensorView.from_record(record, now=now) for record in sensors]


@router.post("/sensors", status_code=201)
async def add_sensor(body: SensorCreate, container: ContainerDep) -> SensorView:
    try:
        async with container.db.session() as session:
            if (
                body.room_id is not None
                and await RoomRepo(session).get(body.room_id) is None
            ):
                raise HTTPException(status_code=404, detail="комната не найдена")
            record = await SensorRepo(session).create(
                kind=KIND_MQTT, name=body.name, source_key=body.source_key
            )
            record.room_id = body.room_id
            view = SensorView.from_record(record, now=time.time())
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="датчик с таким топиком уже есть"
        ) from exc
    container.events.publish(TOPIC_DEVICE_LIST_CHANGED, {"sensor_id": view.id})
    return view


@router.patch("/sensors/{sensor_id}")
async def update_sensor(
    sensor_id: int, body: SensorUpdate, container: ContainerDep
) -> SensorView:
    async with container.db.session() as session:
        record = await SensorRepo(session).get(sensor_id)
        if record is None:
            raise HTTPException(status_code=404, detail="датчик не найден")
        if body.name is not None:
            record.name = body.name
        if body.room_id is not None:
            if await RoomRepo(session).get(body.room_id) is None:
                raise HTTPException(status_code=404, detail="комната не найдена")
            record.room_id = body.room_id
        view = SensorView.from_record(record, now=time.time())
    container.events.publish(TOPIC_DEVICE_LIST_CHANGED, {"sensor_id": sensor_id})
    return view


@router.delete("/sensors/{sensor_id}", status_code=204)
async def remove_sensor(sensor_id: int, container: ContainerDep) -> None:
    """Удаляет датчик; его триггеры уходят каскадом (FK)."""
    async with container.db.session() as session:
        repo = SensorRepo(session)
        record = await repo.get(sensor_id)
        if record is None:
            raise HTTPException(status_code=404, detail="датчик не найден")
        await repo.delete(record)
    container.events.publish(TOPIC_DEVICE_LIST_CHANGED, {"sensor_id": sensor_id})
    _notify_changed(container, "trigger", "deleted", sensor_id)


# --- триггеры ---------------------------------------------------------------


@router.get("/triggers")
async def list_triggers(container: ContainerDep) -> list[TriggerView]:
    async with container.db.session() as session:
        triggers = await TriggerRepo(session).list_all()
    return [TriggerView.from_record(record) for record in triggers]


@router.post("/triggers", status_code=201)
async def add_trigger(body: TriggerBody, container: ContainerDep) -> TriggerView:
    await _check_trigger_refs(container, body)
    async with container.db.session() as session:
        record = await TriggerRepo(session).create(**body.stored_fields())
        view = TriggerView.from_record(record)
    _notify_changed(container, "trigger", "created", view.id)
    return view


@router.put("/triggers/{trigger_id}")
async def update_trigger(
    trigger_id: int, body: TriggerBody, container: ContainerDep
) -> TriggerView:
    await _check_trigger_refs(container, body)
    async with container.db.session() as session:
        record = await TriggerRepo(session).get(trigger_id)
        if record is None:
            raise HTTPException(status_code=404, detail="триггер не найден")
        for field, value in body.stored_fields().items():
            setattr(record, field, value)
        record.is_active = False  # условие изменилось — защёлка с чистого листа
        view = TriggerView.from_record(record)
    _notify_changed(container, "trigger", "updated", trigger_id)
    return view


@router.delete("/triggers/{trigger_id}", status_code=204)
async def remove_trigger(trigger_id: int, container: ContainerDep) -> None:
    async with container.db.session() as session:
        repo = TriggerRepo(session)
        record = await repo.get(trigger_id)
        if record is None:
            raise HTTPException(status_code=404, detail="триггер не найден")
        await repo.delete(record)
    _notify_changed(container, "trigger", "deleted", trigger_id)
