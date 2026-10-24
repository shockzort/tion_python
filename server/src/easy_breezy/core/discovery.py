"""Общий контракт поиска датчиков: провайдеры отдают найденное единым видом.

UI не знает конкретных моделей: «поиск → выбрать → добавить» работает для
любого провайдера, реализующего ``SensorDiscovery``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class DiscoveredSensor:
    """Найденный, но не обязательно зарегистрированный источник показаний."""

    kind: str
    source_key: str
    address: str
    """Человекочитаемый идентификатор (MAC, топик) — для подписи в UI."""
    model: str | None
    signal_dbm: int | None
    metrics: dict[str, float]
    registered: bool


class SensorDiscovery(Protocol):
    """Провайдер, умеющий искать датчики без их регистрации."""

    async def discover(self) -> list[DiscoveredSensor]:
        """Найденные источники; ошибка недоступности — ``ValueError``."""
        ...
