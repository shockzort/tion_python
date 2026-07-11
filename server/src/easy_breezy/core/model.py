"""Общие типы ядра: дельта состояния и сериализация состояния.

Дельта — частичное намерение («что изменить»); полный набор для SET_PARAMS
собирает command bus, мержа дельту поверх последнего подтверждённого
состояния (ADR-0004, план §8).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from easy_breezy.ble.protocol.s4 import Mode, S4State


class DeltaError(ValueError):
    """Дельта не разбирается или содержит недопустимые поля."""


@dataclass(frozen=True, slots=True)
class StateDelta:
    """Частичное изменение состояния бризера; None — поле не трогать."""

    power: bool | None = None
    sound: bool | None = None
    light: bool | None = None
    heater: bool | None = None
    mode: Mode | None = None
    heater_temp: int | None = None
    fan_speed: int | None = None

    def is_empty(self) -> bool:
        return all(
            getattr(self, field.name) is None for field in dataclasses.fields(self)
        )

    def apply_to(self, state: S4State) -> S4State:
        """Полный набор параметров: дельта поверх фактического состояния."""
        changes = {
            field.name: value
            for field in dataclasses.fields(self)
            if (value := getattr(self, field.name)) is not None
        }
        return dataclasses.replace(state, **changes)

    def to_payload(self) -> dict[str, Any]:
        """JSON для журнала команд (только заданные поля)."""
        payload: dict[str, Any] = {}
        for field in dataclasses.fields(self):
            value = getattr(self, field.name)
            if value is None:
                continue
            payload[field.name] = value.value if isinstance(value, Mode) else value
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> StateDelta:
        """Разбирает дельту из JSON (журнал/REST); лишние ключи — ошибка."""
        known = {field.name for field in dataclasses.fields(cls)}
        unknown = set(payload) - known
        if unknown:
            raise DeltaError(f"неизвестные поля дельты: {sorted(unknown)}")
        values = dict(payload)
        if "mode" in values and values["mode"] is not None:
            try:
                values["mode"] = Mode(values["mode"])
            except ValueError as exc:
                raise DeltaError(f"недопустимый mode: {values['mode']!r}") from exc
        try:
            return cls(**values)
        except TypeError as exc:  # pragma: no cover — защита от кривых типов
            raise DeltaError(str(exc)) from exc


def state_to_dict(state: S4State) -> dict[str, Any]:
    """Состояние → JSON для журнала, REST и WS."""
    return {
        "power": state.power,
        "sound": state.sound,
        "light": state.light,
        "heater": state.heater,
        "mode": state.mode.value,
        "heater_temp": state.heater_temp,
        "fan_speed": state.fan_speed,
        "in_temp": state.in_temp,
        "out_temp": state.out_temp,
        "filter_remain_days": round(state.filter_remain_days, 1),
    }
