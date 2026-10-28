"""Настройки Qingping CGDN1 по MQTT: пересчёт между датчиком и сервисом.

Датчик отдаёт конфиг ответом ``type=28`` (на запрос ``{"type":"28"}`` и на
каждую запись) и принимает изменения командой ``type=17`` с объектом
``setting`` (docs/qingping.md). Единицы датчика неудобны: поправка
температуры ×100, влажности ×10, часовой пояс в десятых часа, пороги
подсветки строкой ``"1000,2000,3000"``. Модуль чистый: только пересчёт.

Яркости экрана в протоколе нет — ни в описании, ни в ответе прошивки 4.8.5.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

SCREENSAVERS = {"rotate": 0, "current": 1, "time_rotate": 2, "time_current": 3}
"""``screensaver_type``: карусель, текущий показатель, время + то же."""


def _scaled(factor: int) -> tuple[Callable[[Any], Any], Callable[[Any], Any]]:
    return (
        lambda raw: round(int(raw) / factor, 2),
        lambda value: round(float(value) * factor),
    )


def _thresholds() -> tuple[Callable[[Any], Any], Callable[[Any], Any]]:
    return (
        lambda raw: [int(part) for part in str(raw).split(",") if part.strip()],
        lambda value: ",".join(str(int(part)) for part in value),
    )


def _flag() -> tuple[Callable[[Any], Any], Callable[[Any], Any]]:
    return (lambda raw: bool(raw), lambda value: 1 if value else 0)


def _enum(table: dict[str, int]) -> tuple[Callable[[Any], Any], Callable[[Any], Any]]:
    by_raw = {raw: name for name, raw in table.items()}
    return (lambda raw: by_raw.get(int(raw), "unknown"), lambda value: table[value])


def _same() -> tuple[Callable[[Any], Any], Callable[[Any], Any]]:
    return (lambda raw: raw, lambda value: value)


# поле сервиса → (ключ датчика, (из датчика, в датчик))
FIELDS: dict[str, tuple[str, tuple[Callable[[Any], Any], Callable[[Any], Any]]]] = {
    "screensaver": ("screensaver_type", _enum(SCREENSAVERS)),
    "display_off_time": ("display_off_time", _same()),
    "auto_slide_time": ("auto_slideing_time", _same()),
    "power_off_time": ("power_off_time", _same()),
    "night_start": ("night_mode_start_time", _same()),
    "night_end": ("night_mode_end_time", _same()),
    "temperature_unit": ("temperature_unit", _same()),
    "is_12_hour": ("is_12_hour_mode", _flag()),
    "timezone": ("timezone", _scaled(10)),
    "co2_asc": ("co2_asc", _flag()),
    "temperature_offset": ("temperature_offset", _scaled(100)),
    "humidity_offset": ("humidity_offset", _scaled(10)),
    "co2_offset": ("co2_offset", _same()),
    "pm25_offset": ("pm25_offset", _same()),
    "pm10_offset": ("pm10_offset", _same()),
    "co2_led_th": ("co2_led_th", _thresholds()),
    "pm25_led_th": ("pm25_led_th", _thresholds()),
}


def from_device(setting: dict[str, Any]) -> dict[str, Any]:
    """Конфиг ``type=28`` → поля сервиса; чего датчик не прислал — нет."""
    result: dict[str, Any] = {}
    for name, (key, (decode, _encode)) in FIELDS.items():
        if key in setting:
            try:
                result[name] = decode(setting[key])
            except (TypeError, ValueError):
                continue  # незнакомый формат прошивки — поле просто не показываем
    return result


def to_device(changes: dict[str, Any]) -> dict[str, Any]:
    """Изменения в полях сервиса → объект ``setting`` для ``type=17``."""
    unknown = set(changes) - set(FIELDS)
    if unknown:
        raise ValueError(f"неизвестные настройки: {sorted(unknown)}")
    return {
        FIELDS[name][0]: FIELDS[name][1][1](value) for name, value in changes.items()
    }
