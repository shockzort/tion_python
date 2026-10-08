"""Watchdog доступности BLE (NFR-4, план §7).

Эскалация при полном молчании эфира: все сопряжённые бризеры офлайн
дольше 10 минут → power-cycle BLE-адаптера через BlueZ D-Bus → ещё
10 минут тишины → SIGTERM самому себе, дальше поднимает Docker.

Каждый тик пингует systemd-watchdog (WATCHDOG=1): зависание event loop
диагностирует сам systemd (WatchdogSec=60 → SIGABRT → рестарт).
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from collections.abc import Awaitable, Callable

import structlog

from easy_breezy.automation.clock import Clock
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.sdnotify import WATCHDOG, sd_notify

log = structlog.get_logger(__name__)

CHECK_INTERVAL_SECONDS = 30.0
ALL_OFFLINE_GRACE_SECONDS = 600.0
DBUS_TIMEOUT_SECONDS = 5.0
ADAPTER_RESET_TIMEOUT_SECONDS = 20.0


def _terminate_self() -> None:
    os.kill(os.getpid(), signal.SIGTERM)


async def reset_bluetooth_adapters() -> bool:
    """Power-cycle всех адаптеров BlueZ; False — адаптеров нет или D-Bus недоступен."""
    from dbus_fast import BusType, Variant
    from dbus_fast.aio import MessageBus

    bus = MessageBus(bus_type=BusType.SYSTEM)
    try:
        async with asyncio.timeout(DBUS_TIMEOUT_SECONDS):
            await bus.connect()
            introspection = await bus.introspect("org.bluez", "/")
            root = bus.get_proxy_object("org.bluez", "/", introspection)
            manager = root.get_interface("org.freedesktop.DBus.ObjectManager")
            objects = await manager.call_get_managed_objects()  # type: ignore[attr-defined]
        adapters = [
            path for path, ifaces in objects.items() if "org.bluez.Adapter1" in ifaces
        ]
        for path in adapters:
            async with asyncio.timeout(DBUS_TIMEOUT_SECONDS):
                proxy = bus.get_proxy_object(
                    "org.bluez", path, await bus.introspect("org.bluez", path)
                )
            props = proxy.get_interface("org.freedesktop.DBus.Properties")
            try:
                async with asyncio.timeout(DBUS_TIMEOUT_SECONDS):
                    await props.call_set(  # type: ignore[attr-defined]
                        "org.bluez.Adapter1", "Powered", Variant("b", False)
                    )
                await asyncio.sleep(1.0)
            finally:
                # Даже при отмене watchdog/таймауте off пытаемся вернуть питание.
                async with asyncio.timeout(DBUS_TIMEOUT_SECONDS):
                    await props.call_set(  # type: ignore[attr-defined]
                        "org.bluez.Adapter1", "Powered", Variant("b", True)
                    )
            log.warning("ble_adapter_power_cycled", adapter=path)
        return bool(adapters)
    finally:
        bus.disconnect()


class BleWatchdog:
    def __init__(
        self,
        connections: Callable[[], dict[str, ConnectionState]],
        clock: Clock,
        *,
        adapter_reset: Callable[[], Awaitable[bool]] = reset_bluetooth_adapters,
        terminate: Callable[[], None] = _terminate_self,
        notify: Callable[[str], bool] = sd_notify,
        grace_seconds: float = ALL_OFFLINE_GRACE_SECONDS,
        check_interval: float = CHECK_INTERVAL_SECONDS,
    ) -> None:
        self._connections = connections
        self._clock = clock
        self._adapter_reset = adapter_reset
        self._terminate = terminate
        self._notify = notify
        self._grace = grace_seconds
        self._interval = check_interval
        self._task: asyncio.Task[None] | None = None
        self._offline_since: float | None = None
        self._reset_attempted = False

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="ble-watchdog")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            await self._clock.sleep(self._interval)
            self._notify(WATCHDOG)
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                # watchdog не имеет права умирать молча (ADR-0007)
                log.exception("watchdog_check_crashed")

    async def check_once(self) -> None:
        """Один шаг эскалации; выделен для time-travel тестов."""
        connections = self._connections()
        someone_online = any(
            state is ConnectionState.ONLINE for state in connections.values()
        )
        if not connections or someone_online:
            if self._offline_since is not None:
                log.info("watchdog_recovered")
            self._offline_since = None
            self._reset_attempted = False
            return

        now = self._clock.now()
        if self._offline_since is None:
            self._offline_since = now
            return
        if now - self._offline_since < self._grace:
            return

        if not self._reset_attempted:
            self._reset_attempted = True
            self._offline_since = now  # адаптеру — свежий грейс после ресета
            log.warning("watchdog_adapter_reset", offline_devices=len(connections))
            try:
                async with asyncio.timeout(ADAPTER_RESET_TIMEOUT_SECONDS):
                    await self._adapter_reset()
            except Exception:
                log.exception("watchdog_adapter_reset_failed")
            return

        log.critical(
            "watchdog_restart_service",
            reason="все бризеры офлайн после сброса адаптера",
        )
        self._terminate()
