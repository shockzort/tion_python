"""Модель ``xiaomi.humidifier.ha2`` — Mijia Purifying Humidifier 3 Pro.

Карта MIoT-свойств (siid/piid) сверена с устройством владельца (прошивка
1.0.9, MCU 0048): все свойства ниже читаются с ``code=0``. Полная
спецификация — home.miot-spec.com/spec/xiaomi.humidifier.ha2 и
``docs/protocol/xiaomi-miio.md`` §3.

Модуль чистый: разбор ответа ``get_properties`` в состояние и сборка
параметров ``set_properties`` из дельты.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

MODEL = "xiaomi.humidifier.ha2"


class ApplianceDeltaError(ValueError):
    """Дельта не разбирается или выходит за допустимые значения."""


FUNCTIONS = {"purify": 0, "humidify": 1}
"""9:5 — функция прибора: очистка или увлажнение."""
HUMIDIFIER_MODES = {"constant": 0, "sleep": 1, "favorite": 2, "fan": 3}
"""2:3 — постоянная влажность, сон, избранный, по скорости."""
PURIFIER_MODES = {"auto": 0, "sleep": 1, "favorite": 2, "fan": 3}
"""11:4 — авто, сон, избранный, по скорости."""
TARGET_HUMIDITY_RANGE = (40, 70)
FAN_LEVELS = (1, 2, 3)
"""Скорость в UI 1..3; на устройстве 0..2 (2:14 и 11:3)."""
WATER_STATES = {-2: "no_tank", -1: "low", 0: "normal", 1: "full"}
"""9:11 — состояние воды в режиме увлажнения."""

# имя поля состояния → (siid, piid)
PROPS: dict[str, tuple[int, int]] = {
    "power": (2, 1),
    "fault": (2, 2),
    "humidifier_mode": (2, 3),
    "target_humidity": (2, 6),
    "water_level": (2, 7),
    "humidifier_fan_level": (2, 14),
    "humidity": (3, 1),
    "air_quality": (3, 3),
    "pm25": (3, 4),
    "pm1": (3, 6),
    "temperature": (3, 7),
    "purifier_filter_life": (4, 1),
    "humidifier_filter_life": (15, 1),
    "screen": (5, 1),
    "sound": (6, 1),
    "child_lock": (7, 1),
    "function": (9, 5),
    "water_state": (9, 11),
    "purifier_fan_level": (11, 3),
    "purifier_mode": (11, 4),
}
_BY_PAIR = {pair: name for name, pair in PROPS.items()}


def _name_of(table: dict[str, int], value: Any, field: str) -> str:
    for name, raw in table.items():
        if raw == value:
            return name
    raise ApplianceDeltaError(f"{field}: неизвестное значение устройства {value!r}")


@dataclass(frozen=True, slots=True)
class Ha2State:
    """Состояние прибора в терминах сервиса (а не siid/piid)."""

    power: bool
    function: str
    humidifier_mode: str
    purifier_mode: str
    target_humidity: int
    humidifier_fan_level: int
    purifier_fan_level: int
    water_level: int
    water_state: str
    fault: int
    humidity: int
    temperature: float
    pm25: int
    pm1: int
    air_quality: int
    purifier_filter_life: int
    humidifier_filter_life: int
    screen: bool
    sound: bool
    child_lock: bool

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def sensor_metrics(self) -> dict[str, float]:
        """Показания для реестра датчиков (графики и триггеры)."""
        return {
            "humidity": float(self.humidity),
            "temperature": float(self.temperature),
            "pm25": float(self.pm25),
        }


def property_request() -> list[dict[str, Any]]:
    """Параметры ``get_properties`` для полного опроса."""
    return [
        {"did": name, "siid": siid, "piid": piid}
        for name, (siid, piid) in PROPS.items()
    ]


def parse_properties(result: list[Any]) -> Ha2State:
    """Ответ ``get_properties`` → состояние; пропуск свойства — ошибка."""
    raw: dict[str, Any] = {}
    for item in result:
        if not isinstance(item, dict) or item.get("code") != 0:
            continue
        name = _BY_PAIR.get((item.get("siid"), item.get("piid")))  # type: ignore[arg-type]
        if name is not None:
            raw[name] = item.get("value")
    missing = sorted(set(PROPS) - set(raw))
    if missing:
        raise ApplianceDeltaError(f"устройство не вернуло свойства: {missing}")
    return Ha2State(
        power=bool(raw["power"]),
        function=_name_of(FUNCTIONS, raw["function"], "function"),
        humidifier_mode=_name_of(HUMIDIFIER_MODES, raw["humidifier_mode"], "mode"),
        purifier_mode=_name_of(PURIFIER_MODES, raw["purifier_mode"], "mode"),
        target_humidity=int(raw["target_humidity"]),
        humidifier_fan_level=int(raw["humidifier_fan_level"]) + 1,
        purifier_fan_level=int(raw["purifier_fan_level"]) + 1,
        water_level=int(raw["water_level"]),
        water_state=WATER_STATES.get(int(raw["water_state"]), "unknown"),
        fault=int(raw["fault"]),
        humidity=int(raw["humidity"]),
        temperature=round(float(raw["temperature"]), 1),
        pm25=int(raw["pm25"]),
        pm1=int(raw["pm1"]),
        air_quality=int(raw["air_quality"]),
        purifier_filter_life=int(raw["purifier_filter_life"]),
        humidifier_filter_life=int(raw["humidifier_filter_life"]),
        screen=bool(raw["screen"]),
        sound=bool(raw["sound"]),
        child_lock=bool(raw["child_lock"]),
    )


@dataclass(frozen=True, slots=True)
class Ha2Delta:
    """Частичное изменение прибора; None — поле не трогать."""

    power: bool | None = None
    function: str | None = None
    humidifier_mode: str | None = None
    purifier_mode: str | None = None
    target_humidity: int | None = None
    humidifier_fan_level: int | None = None
    purifier_fan_level: int | None = None
    screen: bool | None = None
    sound: bool | None = None
    child_lock: bool | None = None

    def is_empty(self) -> bool:
        return all(
            getattr(self, field.name) is None for field in dataclasses.fields(self)
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            field.name: value
            for field in dataclasses.fields(self)
            if (value := getattr(self, field.name)) is not None
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Ha2Delta:
        """Разбирает и проверяет дельту; лишние ключи и кривые значения — ошибка."""
        known = {field.name for field in dataclasses.fields(cls)}
        unknown = set(payload) - known
        if unknown:
            raise ApplianceDeltaError(f"неизвестные поля дельты: {sorted(unknown)}")
        delta = cls(**payload)
        delta._validate()
        return delta

    def _validate(self) -> None:
        for name in ("power", "screen", "sound", "child_lock"):
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise ApplianceDeltaError(f"{name}: нужен bool")
        choices = {
            "function": FUNCTIONS,
            "humidifier_mode": HUMIDIFIER_MODES,
            "purifier_mode": PURIFIER_MODES,
        }
        for name, table in choices.items():
            value = getattr(self, name)
            if value is not None and value not in table:
                raise ApplianceDeltaError(
                    f"{name}: одно из {sorted(table)}, получено {value!r}"
                )
        low, high = TARGET_HUMIDITY_RANGE
        if self.target_humidity is not None and (
            isinstance(self.target_humidity, bool)
            or not isinstance(self.target_humidity, int)
            or not low <= self.target_humidity <= high
        ):
            raise ApplianceDeltaError(f"target_humidity: целое {low}..{high}")
        for name in ("humidifier_fan_level", "purifier_fan_level"):
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool) or value not in FAN_LEVELS
            ):
                raise ApplianceDeltaError(f"{name}: одно из {list(FAN_LEVELS)}")

    def to_properties(self) -> list[dict[str, Any]]:
        """Параметры ``set_properties``; функция идёт первой — режимы зависят от неё."""
        values: dict[str, Any] = {}
        if self.function is not None:
            values["function"] = FUNCTIONS[self.function]
        if self.power is not None:
            values["power"] = self.power
        if self.humidifier_mode is not None:
            values["humidifier_mode"] = HUMIDIFIER_MODES[self.humidifier_mode]
        if self.purifier_mode is not None:
            values["purifier_mode"] = PURIFIER_MODES[self.purifier_mode]
        if self.target_humidity is not None:
            values["target_humidity"] = self.target_humidity
        if self.humidifier_fan_level is not None:
            values["humidifier_fan_level"] = self.humidifier_fan_level - 1
        if self.purifier_fan_level is not None:
            values["purifier_fan_level"] = self.purifier_fan_level - 1
        for name in ("screen", "sound", "child_lock"):
            if (value := getattr(self, name)) is not None:
                values[name] = value
        return [
            {
                "did": name,
                "siid": PROPS[name][0],
                "piid": PROPS[name][1],
                "value": value,
            }
            for name, value in values.items()
        ]
