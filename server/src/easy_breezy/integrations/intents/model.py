"""Модель интентов: каталог сущностей и результаты разбора (FR-30).

Контракт двух сторон: парсер (rules сейчас, LLM позже) получает ``Catalog``
и возвращает один из исходов разбора; исполнение и человекочитаемый ответ —
забота ``IntentService``. Парсер чистый — без I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class CatalogDevice:
    uuid: str
    name: str
    room: str | None


@dataclass(frozen=True, slots=True)
class CatalogScenario:
    id: int
    name: str


@dataclass(frozen=True, slots=True)
class CatalogSensor:
    id: int
    name: str
    room: str | None
    values: dict[str, float] = field(default_factory=dict)
    stale: bool = True


@dataclass(frozen=True, slots=True)
class Catalog:
    """Всё, на что можно сослаться голосом; собирается сервисом из БД."""

    devices: list[CatalogDevice]
    scenarios: list[CatalogScenario]
    sensors: list[CatalogSensor]


@dataclass(frozen=True, slots=True)
class DeviceCommandIntent:
    """Команда бризерам: дельта + резолвнутые цели."""

    device_uuids: list[str]
    delta_payload: dict[str, Any]
    description: str
    """Человекочитаемо: «скорость 3, нагрев вкл»."""
    target_label: str
    """Человекочитаемо: «Спальня» / «все бризеры»."""


@dataclass(frozen=True, slots=True)
class ScenarioIntent:
    scenario_id: int
    name: str


@dataclass(frozen=True, slots=True)
class StatusIntent:
    """Запрос состояния; None в metric — сводка по всем метрикам."""

    metric: str | None
    room: str | None


@dataclass(frozen=True, slots=True)
class Clarification:
    """Разбор неоднозначен — переспросить, ничего не исполняя (FR-31)."""

    reply: str


ParseOutcome = (
    DeviceCommandIntent | ScenarioIntent | StatusIntent | Clarification | None
)


class IntentProvider(Protocol):
    """Сменный разборщик: v1 — правила, v2 — локальный LLM (тот же контракт)."""

    def parse(self, text: str, catalog: Catalog) -> ParseOutcome: ...
