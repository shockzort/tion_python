"""Модель ``xiaomi.humidifier.ha2`` — Mijia Purifying Humidifier 3 Pro.

Карта MIoT-свойств (siid/piid) сверена с устройством владельца (прошивка
1.0.9, MCU 0048): все свойства ниже читаются с ``code=0``. Полная
спецификация — home.miot-spec.com/spec/xiaomi.humidifier.ha2 и
``docs/protocol/xiaomi-miio.md`` §3.

Модуль чистый: разбор ответа ``get_properties`` в состояние, сборка
параметров ``set_properties`` из дельты и ``action`` для обслуживания.

Ночной режим (9:6–9:8) в спецификации без названий: смысл выведен по
значениям устройства (вкл, 1380 и 600 минут — 23:00–10:00).
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
SCREEN_BRIGHTNESS = {"auto": 0, "bright": 1, "medium": 2, "dim": 3}
"""5:2 — яркость экрана."""
DISPLAY_METRICS = {"pm25": 0, "pm1": 1, "pm10": 2}
"""9:21 — какой показатель частиц на экране."""
STATUSES = {
    0: "idle",
    1: "drying",
    2: "cleaning",
    3: "clean_interrupted",
    4: "clean_finished",
}
"""2:13 — служебное состояние: сушка, самоочистка."""
FAVORITE_LEVEL_RANGE = (0, 9)
"""10:1 — скорость избранного режима очистки."""
OFF_TIMER_HOURS_RANGE = (1, 8)
MINUTES_IN_DAY = 1440

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
    # настройки и служебное
    "screen_brightness": (5, 2),
    "auto_dry": (2, 11),
    "dry_remaining": (2, 12),
    "overwet_protect": (2, 10),
    "status": (2, 13),
    "clean_remaining": (12, 3),
    "purifier_favorite_level": (10, 1),
    "off_timer": (13, 1),
    "off_timer_hours": (13, 2),
    "off_timer_remaining": (13, 3),
    "night_mode": (9, 6),
    "night_start": (9, 7),
    "night_end": (9, 8),
    "display_metric": (9, 21),
}
_BY_PAIR = {pair: name for name, pair in PROPS.items()}
_BOOL_FIELDS = (
    "power",
    "screen",
    "sound",
    "child_lock",
    "auto_dry",
    "overwet_protect",
    "off_timer",
    "night_mode",
)

ACTIONS: dict[str, tuple[int, int]] = {
    "self_clean_start": (12, 1),
    "self_clean_stop": (12, 2),
    "dry_start": (9, 7),
    "dry_stop": (9, 8),
    "reset_purifier_filter": (4, 1),
    "reset_humidifier_filter": (15, 1),
}
"""Действия обслуживания → (siid, aiid) для метода ``action``."""


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
    screen_brightness: str
    auto_dry: bool
    dry_remaining: int
    """Минут до конца сушки фильтра."""
    overwet_protect: bool
    status: str
    clean_remaining: int
    """Минут до конца самоочистки."""
    purifier_favorite_level: int
    off_timer: bool
    off_timer_hours: int
    off_timer_remaining: int
    """Минут до выключения по таймеру."""
    night_mode: bool
    night_start: int
    """Начало ночного режима, минуты от полуночи."""
    night_end: int
    display_metric: str

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
        screen_brightness=_name_of(
            SCREEN_BRIGHTNESS, raw["screen_brightness"], "screen_brightness"
        ),
        auto_dry=bool(raw["auto_dry"]),
        dry_remaining=int(raw["dry_remaining"]),
        overwet_protect=bool(raw["overwet_protect"]),
        status=STATUSES.get(int(raw["status"]), "unknown"),
        clean_remaining=int(raw["clean_remaining"]),
        purifier_favorite_level=int(raw["purifier_favorite_level"]),
        off_timer=bool(raw["off_timer"]),
        off_timer_hours=int(raw["off_timer_hours"]),
        off_timer_remaining=int(raw["off_timer_remaining"]),
        night_mode=bool(raw["night_mode"]),
        night_start=int(raw["night_start"]),
        night_end=int(raw["night_end"]),
        display_metric=_name_of(
            DISPLAY_METRICS, raw["display_metric"], "display_metric"
        ),
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
    screen_brightness: str | None = None
    auto_dry: bool | None = None
    overwet_protect: bool | None = None
    purifier_favorite_level: int | None = None
    off_timer: bool | None = None
    off_timer_hours: int | None = None
    night_mode: bool | None = None
    night_start: int | None = None
    night_end: int | None = None
    display_metric: str | None = None

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
        for name in _BOOL_FIELDS:
            value = getattr(self, name)
            if value is not None and not isinstance(value, bool):
                raise ApplianceDeltaError(f"{name}: нужен bool")
        choices = {
            "function": FUNCTIONS,
            "humidifier_mode": HUMIDIFIER_MODES,
            "purifier_mode": PURIFIER_MODES,
            "screen_brightness": SCREEN_BRIGHTNESS,
            "display_metric": DISPLAY_METRICS,
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
        ranges = {
            "purifier_favorite_level": FAVORITE_LEVEL_RANGE,
            "off_timer_hours": OFF_TIMER_HOURS_RANGE,
            "night_start": (0, MINUTES_IN_DAY - 1),
            "night_end": (0, MINUTES_IN_DAY - 1),
        }
        for name, (low, high) in ranges.items():
            value = getattr(self, name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or not low <= value <= high
            ):
                raise ApplianceDeltaError(f"{name}: целое {low}..{high}")

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
        if self.screen_brightness is not None:
            values["screen_brightness"] = SCREEN_BRIGHTNESS[self.screen_brightness]
        if self.display_metric is not None:
            values["display_metric"] = DISPLAY_METRICS[self.display_metric]
        # длительность таймера и часы ночного режима — до включения, иначе
        # прибор стартует со старыми значениями
        passthrough = (
            "screen",
            "sound",
            "child_lock",
            "auto_dry",
            "overwet_protect",
            "purifier_favorite_level",
            "off_timer_hours",
            "off_timer",
            "night_start",
            "night_end",
            "night_mode",
        )
        for name in passthrough:
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


def action_request(name: str) -> dict[str, Any]:
    """Параметры метода ``action`` для действия обслуживания."""
    if name not in ACTIONS:
        raise ApplianceDeltaError(f"действие: одно из {sorted(ACTIONS)}")
    siid, aiid = ACTIONS[name]
    return {"did": name, "siid": siid, "aiid": aiid, "in": []}
