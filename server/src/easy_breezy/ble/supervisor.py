"""Супервизор соединения: держит бризер на связи, переподключается с backoff.

Машина состояний (план §7): DISCONNECTED → CONNECTING → ONLINE; деградация
(3 подряд неудачных опроса) и разрыв ведут к пересозданию соединения.
Время ожидания инжектируется — тесты выполняются мгновенно.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from collections.abc import Awaitable, Callable
from enum import StrEnum

import structlog

from easy_breezy.ble.driver import DriverTimeoutError, S4Driver
from easy_breezy.ble.protocol.framing import ProtocolError
from easy_breezy.ble.protocol.s4 import S4State
from easy_breezy.ble.transport import BleTransport, TransportError

log = structlog.get_logger("easy_breezy.ble")

_MAX_POLL_MISSES = 3


class ConnectionState(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    ONLINE = "online"


class DeviceSupervisor:
    """Задача жизненного цикла одного устройства.

    ``transport_factory`` создаёт свежий транспорт на каждую попытку
    (BleakClient невозобновляем после разрыва). ``scan_gate`` — общий лок:
    активный скан и попытки подключения взаимоисключены (план §7).
    """

    def __init__(
        self,
        transport_factory: Callable[[], BleTransport],
        *,
        poll_interval: float = 30.0,
        backoff_initial: float = 1.0,
        backoff_max: float = 60.0,
        response_timeout: float = 3.0,
        scan_gate: asyncio.Lock | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        on_state: Callable[[S4State], None] | None = None,
        on_connection: Callable[[ConnectionState], None] | None = None,
    ) -> None:
        self._transport_factory = transport_factory
        self._poll_interval = poll_interval
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._response_timeout = response_timeout
        self._scan_gate = scan_gate
        self._sleep = sleep
        self._jitter = jitter
        self._on_state = on_state
        self._on_connection = on_connection
        self._task: asyncio.Task[None] | None = None
        self.connection_state = ConnectionState.DISCONNECTED
        self.last_state: S4State | None = None
        self.address: str | None = None
        self.driver: S4Driver | None = None
        """Драйвер живой сессии (None вне сессии) — точка входа командной шины."""

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run(), name="device-supervisor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._set_connection(ConnectionState.DISCONNECTED)

    async def run(self) -> None:
        """Бесконечный цикл подключения; завершается только отменой."""
        backoff = self._backoff_initial
        while True:
            self._set_connection(ConnectionState.CONNECTING)
            try:
                await self._session()
                backoff = self._backoff_initial  # сессия жила — сброс backoff
            except (TransportError, ProtocolError, DriverTimeoutError, OSError) as exc:
                log.warning(
                    "device_session_failed",
                    address=self.address,
                    error=str(exc),
                )
            self._set_connection(ConnectionState.DISCONNECTED)
            delay = min(backoff, self._backoff_max)
            delay += delay * 0.25 * self._jitter()
            log.debug("reconnect_backoff", address=self.address, delay=round(delay, 2))
            await self._sleep(delay)
            backoff = min(backoff * 2, self._backoff_max)

    async def _session(self) -> None:
        """Одна сессия: подключение → ONLINE → опрос до разрыва/деградации."""
        transport = self._transport_factory()
        self.address = transport.address
        driver = S4Driver(transport, response_timeout=self._response_timeout)
        disconnected = asyncio.Event()
        driver.on_state = self._handle_state
        driver.on_disconnect = disconnected.set

        # гейт держится только на время установления соединения
        if self._scan_gate is not None:
            async with self._scan_gate:
                await driver.start()
        else:
            await driver.start()
        self.driver = driver
        try:
            initial = await driver.get_state()
            log.info("device_online", address=self.address, state=initial)
            self._set_connection(ConnectionState.ONLINE)
            await self._poll_until_lost(driver, disconnected)
        finally:
            self.driver = None
            await driver.close()

    async def _poll_until_lost(
        self, driver: S4Driver, disconnected: asyncio.Event
    ) -> None:
        misses = 0
        while not disconnected.is_set():
            waiter = asyncio.ensure_future(disconnected.wait())
            sleeper = asyncio.ensure_future(self._sleep(self._poll_interval))
            try:
                await asyncio.wait(
                    (waiter, sleeper), return_when=asyncio.FIRST_COMPLETED
                )
            finally:
                waiter.cancel()
                sleeper.cancel()
            if disconnected.is_set():
                break
            try:
                await driver.get_state()
                misses = 0
            except DriverTimeoutError:
                misses += 1
                log.warning("poll_missed", address=self.address, misses=misses)
                if misses >= _MAX_POLL_MISSES:
                    raise
        raise TransportError(f"{self.address}: соединение потеряно")

    def _handle_state(self, state: S4State) -> None:
        self.last_state = state
        if self._on_state is not None:
            self._on_state(state)

    def _set_connection(self, state: ConnectionState) -> None:
        if state is self.connection_state:
            return
        self.connection_state = state
        log.info("connection_state", address=self.address, state=state)
        if self._on_connection is not None:
            self._on_connection(state)
