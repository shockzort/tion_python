"""Rule-based разбор русских команд бризерам (FR-30, план §14.7).

Чистые функции без I/O. Морфология — грубым стем-матчем (общий префикс),
этого хватает для бытовых форм: «в спальне» ↔ комната «Спальня»,
«ночной режим» ↔ сценарий «Ночной режим». Числительные — словарём
(«три», «тройку», «3»). Неоднозначность — честный ``Clarification``,
нераспознанный текст — ``None`` (сервис ответит подсказкой).
"""

from __future__ import annotations

import re
from typing import Any

from easy_breezy.integrations.intents.model import (
    Catalog,
    CatalogDevice,
    Clarification,
    DeviceCommandIntent,
    ParseOutcome,
    ScenarioIntent,
    StatusIntent,
)

_WORD_RE = re.compile(r"[а-яa-z0-9]+")

_STEM_PREFIX = 4
"""Минимальный общий префикс, чтобы считать слова формами одного слова."""

_FAN_WORDS = {
    "1": 1,
    "один": 1,
    "единицу": 1,
    "единичку": 1,
    "первую": 1,
    "2": 2,
    "два": 2,
    "двойку": 2,
    "вторую": 2,
    "3": 3,
    "три": 3,
    "тройку": 3,
    "третью": 3,
    "4": 4,
    "четыре": 4,
    "четверку": 4,
    "четвертую": 4,
    "5": 5,
    "пять": 5,
    "пятерку": 5,
    "пятую": 5,
    "6": 6,
    "шесть": 6,
    "шестерку": 6,
    "шестую": 6,
    "максимум": 6,
}

_ON_STEMS = ("включ", "вруб", "запус", "активир")
_OFF_STEMS = ("выключ", "отключ", "выруб", "останов", "погас")
_ALL_WORDS = ("все", "всем", "всех", "везде", "повсюду", "дом")

_METRIC_MARKERS = {
    "co2": ("co2", "со2", "углекис", "воздух", "духот"),
    "temperature": ("температур", "градус", "тепл"),
    "humidity": ("влажн",),
}
_QUESTION_MARKERS = ("какой", "какая", "какое", "сколько", "покажи", "статус", "что")


def normalize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower().replace("ё", "е"))


def stem_match(word: str, other: str) -> bool:
    """Формы одного слова: равенство или общий префикс ≥ 4 при близкой длине."""
    if word == other:
        return True
    if min(len(word), len(other)) < _STEM_PREFIX:
        return False
    prefix = 0
    for a, b in zip(word, other, strict=False):
        if a != b:
            break
        prefix += 1
    # хвосты-окончания не длиннее 3 символов: «спальн|е» ↔ «спальн|я»
    return prefix >= _STEM_PREFIX and (
        len(word) - prefix <= 3 and len(other) - prefix <= 3
    )


def _name_in_tokens(name: str, tokens: list[str]) -> bool:
    """Все слова имени встречаются в тексте (по стем-матчу, подряд не требуем)."""
    name_words = normalize(name)
    return bool(name_words) and all(
        any(stem_match(token, word) for token in tokens) for word in name_words
    )


def _has_stem(tokens: list[str], stems: tuple[str, ...]) -> bool:
    return any(token.startswith(stem) for token in tokens for stem in stems)


def parse(text: str, catalog: Catalog) -> ParseOutcome:
    tokens = normalize(text)
    if not tokens:
        return None

    scenario = _match_scenario(tokens, catalog)
    if scenario is not None:
        return scenario

    status = _match_status(tokens, catalog)
    if status is not None:
        return status

    return _match_command(text, tokens, catalog)


def _match_scenario(tokens: list[str], catalog: Catalog) -> ScenarioIntent | None:
    """Сценарий по имени; из нескольких совпавших — самое длинное имя."""
    best: ScenarioIntent | None = None
    best_words = 0
    for scenario in catalog.scenarios:
        words = len(normalize(scenario.name))
        if words > best_words and _name_in_tokens(scenario.name, tokens):
            best = ScenarioIntent(scenario.id, scenario.name)
            best_words = words
    return best


def _match_status(tokens: list[str], catalog: Catalog) -> StatusIntent | None:
    if not any(
        stem_match(token, marker) or token.startswith("покаж")
        for token in tokens
        for marker in _QUESTION_MARKERS
    ):
        return None
    metric = next(
        (
            name
            for name, markers in _METRIC_MARKERS.items()
            if _has_stem(tokens, markers)
        ),
        None,
    )
    if metric is None and not _has_stem(tokens, ("состоян", "статус")):
        return None
    return StatusIntent(metric=metric, room=_match_room(tokens, catalog))


def _match_room(tokens: list[str], catalog: Catalog) -> str | None:
    rooms: set[str] = set()
    for device in catalog.devices:
        if device.room is not None:
            rooms.add(device.room)
    for sensor in catalog.sensors:
        if sensor.room is not None:
            rooms.add(sensor.room)
    for room in sorted(rooms):
        if _name_in_tokens(room, tokens):
            return room
    return None


def _build_delta(tokens: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Дельта из токенов + человекочитаемые кусочки описания."""
    delta: dict[str, Any] = {}
    parts: list[str] = []
    on = _has_stem(tokens, _ON_STEMS)
    off = _has_stem(tokens, _OFF_STEMS)

    # скорость: «скорость три», «на тройку», «поставь 4»
    fan = None
    for index, token in enumerate(tokens):
        if token in _FAN_WORDS:
            value = _FAN_WORDS[token]
            # голое число рядом с «градус» — это температура, не скорость
            window = tokens[max(0, index - 2) : index + 2]
            if not _has_stem(window, ("градус",)):
                fan = value
    if fan is not None and (
        _has_stem(tokens, ("скорост", "поставь", "постав", "сдела"))
        or any(token in _FAN_WORDS and not token.isdigit() for token in tokens)
        or on
    ):
        delta["fan_speed"] = fan
        parts.append(f"скорость {fan}")

    # температура: «сделай 22 градуса», «нагрей до 25»
    for index, token in enumerate(tokens):
        if token.isdigit() and 10 <= int(token) <= 30:
            window = tokens[max(0, index - 3) : index + 3]
            if _has_stem(window, ("градус", "температур", "нагрей", "тепл")):
                delta["heater_temp"] = int(token)
                parts.append(f"{token} °C")
                break

    # тумблеры по контексту вкл/выкл
    for stems, field, label in (
        (("нагрев", "обогрев", "подогрев", "нагрей"), "heater", "нагрев"),
        (("звук",), "sound", "звук"),
        (("подсветк", "свет"), "light", "подсветка"),
    ):
        if _has_stem(tokens, stems):
            if field == "heater" and "heater_temp" in delta:
                delta["heater"] = True
                continue
            if off and not on:
                delta[field] = False
                parts.append(f"{label} выкл")
            else:
                delta[field] = True
                parts.append(f"{label} вкл")

    if _has_stem(tokens, ("рециркул",)):
        delta["mode"] = "recirculation"
        parts.append("рециркуляция")
    elif _has_stem(tokens, ("приток", "проветр", "улиц")):
        delta["mode"] = "outside"
        parts.append("приток")

    # голые вкл/выкл без других полей — питание; «выключи звук» питание не трогает
    if off and not on and not delta:
        delta["power"] = False
        parts.append("выключение")
    elif on and not any(field in delta for field in ("heater", "sound", "light")):
        delta.setdefault("power", True)
        if "fan_speed" not in delta and len(delta) == 1:
            parts.insert(0, "включение")

    return delta, parts


def _match_command(text: str, tokens: list[str], catalog: Catalog) -> ParseOutcome:
    delta, parts = _build_delta(tokens)
    if not delta:
        return None

    targets, label = _resolve_targets(tokens, catalog)
    if targets is None:
        names = ", ".join(device.name for device in catalog.devices)
        return Clarification(f"Уточните, какой бризер: {names}. Или скажите «все».")
    return DeviceCommandIntent(
        device_uuids=[device.uuid for device in targets],
        delta_payload=delta,
        description=", ".join(parts) if parts else "команда",
        target_label=label,
    )


def _resolve_targets(
    tokens: list[str], catalog: Catalog
) -> tuple[list[CatalogDevice] | None, str]:
    devices = catalog.devices
    if not devices:
        return None, ""
    if any(token in _ALL_WORDS for token in tokens):
        return devices, "все бризеры"

    by_name = [device for device in devices if _name_in_tokens(device.name, tokens)]
    if len(by_name) == 1:
        return by_name, by_name[0].name

    room = _match_room(tokens, catalog)
    if room is not None:
        in_room = [device for device in devices if device.room == room]
        if in_room:
            return in_room, room

    if len(devices) == 1:
        return devices, devices[0].name
    return None, ""
