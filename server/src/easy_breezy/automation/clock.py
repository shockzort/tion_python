"""Инжектируемое время автоматизации (план §9).

Планировщик и триггеры получают время только через ``Clock`` — time-travel
тесты подменяют его фейком и прокручивают часы без реального ожидания.
"""

from __future__ import annotations

import asyncio
import time
from typing import Protocol


class Clock(Protocol):
    """Источник времени и сна; единственная точка контакта с реальными часами."""

    def now(self) -> float:
        """Текущее unix-время (секунды)."""
        ...

    async def sleep(self, seconds: float) -> None:
        """Приостанавливает вызывающего; отменяется как обычный ``sleep``."""
        ...


class SystemClock:
    """Боевые часы: ``time.time`` + ``asyncio.sleep``."""

    def now(self) -> float:
        return time.time()

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
