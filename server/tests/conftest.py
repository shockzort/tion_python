"""Общие фикстуры: БД во временном файле, ядро на фейках, приложение целиком."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from easy_breezy.app import create_app
from easy_breezy.ble.fake import FakeS4Device, FakeTransport
from easy_breezy.config import Settings
from easy_breezy.container import AppContainer
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


class FakeClock:
    """Часы time-travel: время двигается только ``advance``."""

    def __init__(self, start: float) -> None:
        self._now = start
        self._sleepers: list[tuple[float, asyncio.Future[None]]] = []

    def now(self) -> float:
        return self._now

    async def sleep(self, seconds: float) -> None:
        deadline = self._now + max(seconds, 0.0)
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        entry = (deadline, future)
        self._sleepers.append(entry)
        try:
            await future
        finally:
            if entry in self._sleepers:
                self._sleepers.remove(entry)

    async def advance(self, seconds: float) -> None:
        """Продвигает время, будя спящих по порядку дедлайнов."""
        target = self._now + seconds
        while True:
            due = [entry for entry in self._sleepers if entry[0] <= target]
            if not due:
                break
            deadline = min(entry[0] for entry in due)
            self._now = deadline
            for entry_deadline, future in list(self._sleepers):
                if entry_deadline <= deadline and not future.done():
                    future.set_result(None)
            for _ in range(10):  # дать проснувшимся задачам исполниться
                await asyncio.sleep(0)
        self._now = target
        for _ in range(10):
            await asyncio.sleep(0)


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


# --- приложение целиком (интеграционные тесты) --------------------------------

ClientAndApp = tuple[TestClient, FastAPI]


def test_settings(**overrides: Any) -> Settings:
    """Settings для тестов: локальный ``server/.env`` игнорируется.

    Иначе стендовые значения (например, EB_SESSION_COOKIE_SECURE=true —
    Secure-cookie не ходит по http://testserver) ломают герметичность.
    """
    return Settings(_env_file=None, **overrides)


@pytest.fixture
def client_app(tmp_path: Path) -> Iterator[ClientAndApp]:
    """Настоящий lifespan на фейках: миграции, супервизоры, шина, WS, Яндекс."""
    app = create_app(
        test_settings(
            log_level="WARNING",
            data_dir=tmp_path,
            fake_devices=3,
            yandex_client_id="ya-client",
            yandex_client_secret="ya-secret",
        )
    )
    with TestClient(app) as client:
        yield client, app


def container_of(app: FastAPI) -> AppContainer:
    container: AppContainer = app.state.container
    return container


def bootstrap_admin(client: TestClient, app: FastAPI) -> None:
    """Setup-токен из контейнера → первый админ → cookie в клиенте."""
    setup_token = container_of(app).auth.setup_token
    assert setup_token is not None
    response = client.post(
        "/api/auth/setup",
        json={
            "setup_token": setup_token,
            "username": "admin",
            "password": "password123",
        },
    )
    assert response.status_code == 201, response.text


def wait_devices_online(client: TestClient) -> list[dict[str, Any]]:
    for _ in range(200):
        devices: list[dict[str, Any]] = client.get("/api/devices").json()
        if devices and all(d["connection"] == "online" for d in devices):
            return devices
        time.sleep(0.05)
    raise AssertionError("фейковые бризеры не вышли в online")
