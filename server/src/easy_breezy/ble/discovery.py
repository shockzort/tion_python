"""Ограниченный по времени жизненный цикл сканера BlueZ."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from bleak import BleakScanner
from bleak.exc import BleakError

log = structlog.get_logger("easy_breezy.ble")
SCAN_OPERATION_TIMEOUT = 5.0


@asynccontextmanager
async def scanning(scanner: BleakScanner) -> AsyncIterator[BleakScanner]:
    """Ограничивает start и stop отдельно, включая отмену частичного start."""
    failed = True
    try:
        async with asyncio.timeout(SCAN_OPERATION_TIMEOUT):
            await scanner.start()
        yield scanner
        failed = False
    finally:
        try:
            async with asyncio.timeout(SCAN_OPERATION_TIMEOUT):
                await scanner.stop()
        except (BleakError, OSError, TimeoutError) as exc:
            log.warning(
                "scanner_stop_failed", error=str(exc), error_type=type(exc).__name__
            )
            if not failed:
                raise
