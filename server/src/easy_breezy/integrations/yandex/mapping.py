"""Маппинг Tion S4 ↔ капабилити Умного дома — единственное место истины (§6).

| Функция              | Capability/Property                              |
|----------------------|--------------------------------------------------|
| Вкл/выкл             | on_off                                           |
| Скорость 1–6         | mode.fan_speed: one…six                          |
| Нагрев               | mode.thermostat: heat / fan_only                 |
| Целевая температура  | range.temperature, celsius, 10–30, шаг 1         |
| Звук                 | toggle.mute (инверсия)                           |
| Подсветка            | toggle.backlight                                 |
| Температура притока  | property float.temperature (= out_temp)          |
| Рециркуляция         | в Алису не экспонируется (нет инстанса)          |

Работает над словарём состояния (``state_to_dict``) — тем же, что уходит
в REST/WS/журнал.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from easy_breezy.core.model import StateDelta

DEVICE_TYPE = "devices.types.ventilation"
SENSOR_TYPE = "devices.types.sensor.climate"
"""Климат-датчики (Фаза 6): id вида ``sensor:{N}``, properties по метрикам."""

CAP_ON_OFF = "devices.capabilities.on_off"
CAP_MODE = "devices.capabilities.mode"
CAP_RANGE = "devices.capabilities.range"
CAP_TOGGLE = "devices.capabilities.toggle"
PROP_FLOAT = "devices.properties.float"

FAN_MODES = ("one", "two", "three", "four", "five", "six")
HEATER_TEMP_MIN = 10
HEATER_TEMP_MAX = 30

SENSOR_INSTANCES: dict[str, tuple[str, str]] = {
    "co2": ("co2_level", "unit.ppm"),
    "temperature": ("temperature", "unit.temperature.celsius"),
    "humidity": ("humidity", "unit.percent"),
}

ERROR_INVALID_ACTION = "INVALID_ACTION"
ERROR_INVALID_VALUE = "INVALID_VALUE"


class ActionError(Exception):
    """Капабилити из action не разбирается в дельту."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def device_descriptor(device_id: str, name: str, room: str | None) -> dict[str, Any]:
    """Описание устройства для GET /user/devices."""
    descriptor: dict[str, Any] = {
        "id": device_id,
        "name": name,
        "type": DEVICE_TYPE,
        "capabilities": [
            {"type": CAP_ON_OFF, "retrievable": True},
            {
                "type": CAP_MODE,
                "retrievable": True,
                "parameters": {
                    "instance": "fan_speed",
                    "modes": [{"value": mode} for mode in FAN_MODES],
                },
            },
            {
                "type": CAP_MODE,
                "retrievable": True,
                "parameters": {
                    "instance": "thermostat",
                    "modes": [{"value": "heat"}, {"value": "fan_only"}],
                },
            },
            {
                "type": CAP_RANGE,
                "retrievable": True,
                "parameters": {
                    "instance": "temperature",
                    "unit": "unit.temperature.celsius",
                    "range": {
                        "min": HEATER_TEMP_MIN,
                        "max": HEATER_TEMP_MAX,
                        "precision": 1,
                    },
                },
            },
            {
                "type": CAP_TOGGLE,
                "retrievable": True,
                "parameters": {"instance": "mute"},
            },
            {
                "type": CAP_TOGGLE,
                "retrievable": True,
                "parameters": {"instance": "backlight"},
            },
        ],
        "properties": [
            {
                "type": PROP_FLOAT,
                "retrievable": True,
                "parameters": {
                    "instance": "temperature",
                    "unit": "unit.temperature.celsius",
                },
            }
        ],
    }
    if room is not None:
        descriptor["room"] = room
    return descriptor


def sensor_descriptor(
    sensor_id: str, name: str, room: str | None, metrics: Sequence[str]
) -> dict[str, Any]:
    """Описание климат-датчика для GET /user/devices (properties по метрикам)."""
    descriptor: dict[str, Any] = {
        "id": sensor_id,
        "name": name,
        "type": SENSOR_TYPE,
        "capabilities": [],
        "properties": [
            {
                "type": PROP_FLOAT,
                "retrievable": True,
                "parameters": {"instance": instance, "unit": unit},
            }
            for metric in metrics
            if (pair := SENSOR_INSTANCES.get(metric)) is not None
            for instance, unit in (pair,)
        ],
    }
    if room is not None:
        descriptor["room"] = room
    return descriptor


def sensor_property_states(values: dict[str, Any]) -> list[dict[str, Any]]:
    """Значения датчика для /query и callback state."""
    states: list[dict[str, Any]] = []
    for metric in SENSOR_INSTANCES:
        value = values.get(metric)
        if value is None:
            continue
        instance, _unit = SENSOR_INSTANCES[metric]
        states.append(
            {
                "type": PROP_FLOAT,
                "state": {"instance": instance, "value": float(value)},
            }
        )
    return states


def capability_states(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Значения капабилити для /query и callback state."""
    fan_speed = int(state["fan_speed"])
    fan_index = min(max(fan_speed, 1), len(FAN_MODES)) - 1
    return [
        _cap_state(CAP_ON_OFF, "on", bool(state["power"])),
        _cap_state(CAP_MODE, "fan_speed", FAN_MODES[fan_index]),
        _cap_state(CAP_MODE, "thermostat", "heat" if state["heater"] else "fan_only"),
        _cap_state(CAP_RANGE, "temperature", int(state["heater_temp"])),
        _cap_state(CAP_TOGGLE, "mute", not state["sound"]),
        _cap_state(CAP_TOGGLE, "backlight", bool(state["light"])),
    ]


def property_states(state: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": PROP_FLOAT,
            "state": {"instance": "temperature", "value": float(state["out_temp"])},
        }
    ]


def _cap_state(cap_type: str, instance: str, value: Any) -> dict[str, Any]:
    return {"type": cap_type, "state": {"instance": instance, "value": value}}


def actions_to_delta(
    capabilities: list[dict[str, Any]], current: dict[str, Any] | None
) -> StateDelta:
    """Все капабилити запроса → одна дельта (одна BLE-запись, план §6).

    ``current`` нужен только относительным range-командам («прибавь два
    градуса»); без известного состояния они отклоняются.
    """
    fields: dict[str, Any] = {}
    for capability in capabilities:
        cap_type = capability.get("type", "")
        state = capability.get("state", {})
        instance = state.get("instance", "")
        value = state.get("value")
        if cap_type == CAP_ON_OFF and instance == "on":
            fields["power"] = bool(value)
        elif cap_type == CAP_MODE and instance == "fan_speed":
            if value not in FAN_MODES:
                raise ActionError(
                    ERROR_INVALID_VALUE, f"недопустимая скорость: {value!r}"
                )
            fields["fan_speed"] = FAN_MODES.index(value) + 1
        elif cap_type == CAP_MODE and instance == "thermostat":
            if value not in ("heat", "fan_only"):
                raise ActionError(
                    ERROR_INVALID_VALUE, f"недопустимый режим термостата: {value!r}"
                )
            fields["heater"] = value == "heat"
        elif cap_type == CAP_RANGE and instance == "temperature":
            fields["heater_temp"] = _range_value(state, current)
        elif cap_type == CAP_TOGGLE and instance == "mute":
            fields["sound"] = not bool(value)
        elif cap_type == CAP_TOGGLE and instance == "backlight":
            fields["light"] = bool(value)
        else:
            raise ActionError(
                ERROR_INVALID_ACTION,
                f"капабилити не поддерживается: {cap_type}/{instance}",
            )
    return StateDelta(**fields)


def _range_value(state: dict[str, Any], current: dict[str, Any] | None) -> int:
    value = state.get("value")
    if not isinstance(value, int | float):
        raise ActionError(ERROR_INVALID_VALUE, f"недопустимая температура: {value!r}")
    if state.get("relative"):
        if current is None:
            raise ActionError(
                ERROR_INVALID_VALUE,
                "относительная команда без известного состояния",
            )
        value = int(current["heater_temp"]) + int(value)
    return min(max(int(value), HEATER_TEMP_MIN), HEATER_TEMP_MAX)
