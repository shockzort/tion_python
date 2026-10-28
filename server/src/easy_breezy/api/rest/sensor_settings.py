"""Настройки датчиков на самом устройстве (docs/qingping.md).

Сейчас настраивается Qingping по Wi-Fi/MQTT: экран, ночной режим, поправки
показаний, пороги подсветки. Чтение и запись идут на датчик синхронно (до
10 с) — ответ несёт конфиг, подтверждённый датчиком, а не отправленный.
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from easy_breezy.api.deps import ContainerDep, require_user
from easy_breezy.core.sensors import KIND_QINGPING_MQTT
from easy_breezy.integrations.qingping import settings as qingping_settings
from easy_breezy.integrations.qingping.mqtt import QingpingSettingsError
from easy_breezy.storage.repos import SensorRepo

router = APIRouter(
    prefix="/api", tags=["sensors"], dependencies=[Depends(require_user)]
)


class QingpingSettings(BaseModel):
    """Изменяемые настройки CGDN1 в единицах сервиса; все поля опциональны."""

    model_config = ConfigDict(extra="forbid")

    screensaver: Literal["rotate", "current", "time_rotate", "time_current"] | None = (
        None
    )
    display_off_time: int | None = Field(default=None, ge=0, le=3600)
    """Секунд до гашения экрана при питании от батареи; 0 — не гасить."""
    auto_slide_time: int | None = Field(default=None, ge=0, le=300)
    power_off_time: int | None = Field(default=None, ge=0, le=60)
    """Минут до автовыключения от батареи; 0 — не выключать."""
    night_start: int | None = Field(default=None, ge=0, le=1439)
    night_end: int | None = Field(default=None, ge=0, le=1439)
    """Ночной режим, минуты от полуночи; начало = конец — выключен."""
    temperature_unit: Literal["C", "F"] | None = None
    is_12_hour: bool | None = None
    timezone: float | None = Field(default=None, ge=-12, le=14, multiple_of=0.5)
    co2_asc: bool | None = None
    """Автокалибровка CO₂ по минимуму за неделю."""
    temperature_offset: float | None = Field(default=None, ge=-10, le=10)
    humidity_offset: float | None = Field(default=None, ge=-20, le=20)
    co2_offset: int | None = Field(default=None, ge=-1000, le=1000)
    pm25_offset: int | None = Field(default=None, ge=-100, le=100)
    pm10_offset: int | None = Field(default=None, ge=-100, le=100)
    co2_led_th: list[int] | None = Field(default=None, min_length=3, max_length=3)
    pm25_led_th: list[int] | None = Field(default=None, min_length=5, max_length=5)

    @model_validator(mode="after")
    def _check(self) -> QingpingSettings:
        if not self.model_fields_set:
            raise ValueError("задайте хотя бы одну настройку")
        for name in ("co2_led_th", "pm25_led_th"):
            values = getattr(self, name)
            if values is not None and (
                any(value < 0 for value in values)
                or any(b <= a for a, b in pairwise(values))
            ):
                raise ValueError(f"{name}: пороги по возрастанию")
        return self

    def changes(self) -> dict[str, Any]:
        return self.model_dump(exclude_none=True)


class SensorSettingsView(BaseModel):
    settings: dict[str, Any]


async def _qingping_key(container: ContainerDep, sensor_id: int) -> str:
    async with container.db.session() as session:
        record = await SensorRepo(session).get(sensor_id)
    if record is None:
        raise HTTPException(status_code=404, detail="датчик не найден")
    if record.kind != KIND_QINGPING_MQTT:
        raise HTTPException(
            status_code=400, detail="у этого датчика нет настроек на устройстве"
        )
    return record.source_key


@router.get("/sensors/{sensor_id}/settings")
async def get_sensor_settings(
    sensor_id: int, container: ContainerDep
) -> SensorSettingsView:
    key = await _qingping_key(container, sensor_id)
    try:
        raw = await container.qingping_mqtt.read_settings(key)
    except QingpingSettingsError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    return SensorSettingsView(settings=qingping_settings.from_device(raw))


@router.put("/sensors/{sensor_id}/settings")
async def put_sensor_settings(
    sensor_id: int, body: QingpingSettings, container: ContainerDep
) -> SensorSettingsView:
    key = await _qingping_key(container, sensor_id)
    try:
        raw = await container.qingping_mqtt.write_settings(
            key, qingping_settings.to_device(body.changes())
        )
    except QingpingSettingsError as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    return SensorSettingsView(settings=qingping_settings.from_device(raw))
