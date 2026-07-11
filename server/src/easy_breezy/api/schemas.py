"""Pydantic-схемы REST: устройства, команды, журнал."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from easy_breezy.ble.protocol.s4 import Mode
from easy_breezy.core.bus import CommandOutcome
from easy_breezy.core.model import StateDelta
from easy_breezy.storage.models import CommandRecord, Device

MAC_PATTERN = r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$"


class DeviceView(BaseModel):
    uuid: str
    mac: str
    name: str
    model: str
    room_id: int | None
    paired: bool
    connection: str
    state: dict[str, Any] | None
    state_at: float | None
    hold_until: float | None

    @classmethod
    def build(
        cls,
        device: Device,
        *,
        connection: str,
        state: dict[str, Any] | None,
        state_at: float | None,
        hold_until: float | None,
    ) -> DeviceView:
        return cls(
            uuid=device.uuid,
            mac=device.mac,
            name=device.name,
            model=device.model,
            room_id=device.room_id,
            paired=device.paired,
            connection=connection,
            state=state,
            state_at=state_at,
            hold_until=hold_until,
        )


class DeviceCreate(BaseModel):
    mac: str = Field(pattern=MAC_PATTERN)
    name: str = Field(min_length=1, max_length=100)


class DeviceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    room_id: int | None = None


class CommandBody(BaseModel):
    """Дельта состояния из REST; все поля опциональны, но хотя бы одно нужно."""

    power: bool | None = None
    sound: bool | None = None
    light: bool | None = None
    heater: bool | None = None
    mode: Literal["outside", "recirculation"] | None = None
    heater_temp: int | None = Field(default=None, ge=10, le=30)
    fan_speed: int | None = Field(default=None, ge=1, le=6)

    @model_validator(mode="after")
    def _require_any_field(self) -> CommandBody:
        if self.to_delta().is_empty():
            raise ValueError("задайте хотя бы одно поле команды")
        return self

    def to_delta(self) -> StateDelta:
        return StateDelta(
            power=self.power,
            sound=self.sound,
            light=self.light,
            heater=self.heater,
            mode=Mode(self.mode) if self.mode is not None else None,
            heater_temp=self.heater_temp,
            fan_speed=self.fan_speed,
        )


class CommandResult(BaseModel):
    """Синхронный итог (200) или принятая команда (202, status=pending)."""

    command_id: int
    status: str
    result_state: dict[str, Any] | None = None
    error: str | None = None

    @classmethod
    def from_outcome(cls, outcome: CommandOutcome) -> CommandResult:
        return cls(
            command_id=outcome.command_id,
            status=outcome.status.value,
            result_state=outcome.result_state,
            error=outcome.error,
        )


class GroupCommandResult(BaseModel):
    device_uuid: str
    result: CommandResult | None = None
    rejected: str | None = None
    """Причина, если команда не принята шиной (например, не сопряжено)."""


class CommandView(BaseModel):
    id: int
    device_uuid: str
    source: str
    priority: int
    status: str
    payload: dict[str, Any]
    result_state: dict[str, Any] | None
    error: str | None
    created_at: int
    started_at: int | None
    finished_at: int | None

    @classmethod
    def from_record(cls, record: CommandRecord) -> CommandView:
        return cls(
            id=record.id,
            device_uuid=record.device_uuid,
            source=record.source,
            priority=record.priority,
            status=record.status,
            payload=record.payload,
            result_state=record.result_state,
            error=record.error,
            created_at=record.created_at,
            started_at=record.started_at,
            finished_at=record.finished_at,
        )
