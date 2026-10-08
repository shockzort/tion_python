"""Фоновое BLE-прослушивание уступает поиск и подключение бризерам."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Literal


class ScanCoordinator(asyncio.Lock):
    """Обычный scan_gate для Tion и прерываемая фоновая сессия Qingping.

    Фоновый слушатель обязан остановить сканер перед выходом из ``background``.
    Подключение Tion получит лок только после освобождения адаптера.
    """

    def __init__(self) -> None:
        super().__init__()
        self._foreground = 0
        self._idle = asyncio.Event()
        self._idle.set()
        self._interrupt = asyncio.Event()

    async def acquire(self) -> Literal[True]:
        self._foreground += 1
        self._idle.clear()
        self._interrupt.set()
        try:
            return await super().acquire()
        except BaseException:
            self._foreground -= 1
            if not self._foreground:
                self._idle.set()
            raise

    def release(self) -> None:
        super().release()
        self._foreground -= 1
        if not self._foreground:
            self._idle.set()

    @asynccontextmanager
    async def background(self) -> AsyncIterator[asyncio.Event]:
        """Даёт адаптер до первого запроса Tion; не обгоняет его очередь."""
        while True:
            await self._idle.wait()
            await super().acquire()
            if not self._foreground:
                break
            super().release()
        self._interrupt.clear()
        try:
            yield self._interrupt
        finally:
            super().release()
