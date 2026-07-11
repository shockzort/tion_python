"""Общие фикстуры: БД во временном файле, ядро на фейковых бризерах."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from easy_breezy.ble.fake import FakeS4Device, FakeTransport
from easy_breezy.core.bus import CommandBus
from easy_breezy.core.events import EventBus
from easy_breezy.core.holds import HoldManager
from easy_breezy.core.registry import DeviceRegistry
from easy_breezy.core.state import StateCache
from easy_breezy.storage import Database


async def wait_for_condition(
    predicate: Callable[[], bool], *, timeout: float = 3.0
) -> None:
    """Ждёт истинности условия поллингом (тестовый хелпер)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("условие не наступило за отведённое время")
        await asyncio.sleep(0.01)


@dataclass
class FakeFleet:
    """Фейковые бризеры по MAC: состояние переживает переподключения.

    ``factory`` отдаётся реестру; каждый вызов — свежий транспорт к общему
    ``FakeS4Device``. ``connect_failures[mac]`` заставляет каждый новый
    транспорт падать на connect (вечно недоступное устройство).
    """

    devices: dict[str, FakeS4Device] = field(default_factory=dict)
    transports: dict[str, list[FakeTransport]] = field(default_factory=dict)
    connect_failures: dict[str, int] = field(default_factory=dict)

    def factory(self, mac: str) -> FakeTransport:
        device = self.devices.setdefault(mac, FakeS4Device())
        transport = FakeTransport(device, address=mac)
        transport.connect_failures = self.connect_failures.get(mac, 0)
        self.transports.setdefault(mac, []).append(transport)
        return transport

    def device(self, mac: str) -> FakeS4Device:
        return self.devices[mac]

    def transport(self, mac: str) -> FakeTransport:
        """Последний созданный транспорт (живой в устойчивой сессии)."""
        return self.transports[mac][-1]


@dataclass
class CoreEnv:
    """Собранное ядро на фейках — без API-слоя."""

    db: Database
    events: EventBus
    cache: StateCache
    holds: HoldManager
    registry: DeviceRegistry
    bus: CommandBus
    fleet: FakeFleet


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.migrate()
    yield database
    await database.dispose()


@pytest.fixture
async def core(db: Database) -> AsyncIterator[CoreEnv]:
    events = EventBus()
    cache = StateCache()
    holds = HoldManager(duration_seconds=3600)
    fleet = FakeFleet()
    registry = DeviceRegistry(
        db,
        events,
        cache,
        fleet.factory,
        poll_interval=5.0,  # опрос не должен вмешиваться в сценарии тестов
        backoff_initial=0.01,
        backoff_max=0.05,
        response_timeout=0.15,
    )
    bus = CommandBus(db, registry, events, holds, execute_budget=2.0, max_queue_depth=2)
    await bus.start()
    yield CoreEnv(db, events, cache, holds, registry, bus, fleet)
    await bus.stop()
    await registry.stop()
