"""Сборка подсистем приложения: явная композиция вместо глобалов (план §3).

Контейнер создаётся в lifespan фабрики приложения и кладётся в
``app.state.container``; зависимости API достают его оттуда.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from easy_breezy.auth import AuthService
from easy_breezy.ble.fake import FakeS4Device, FakeTransport, fake_mac
from easy_breezy.ble.protocol.s4 import GATT_NOTIFY, GATT_WRITE
from easy_breezy.ble.transport import BleakTransport, BleTransport
from easy_breezy.config import Settings
from easy_breezy.core.bus import CommandBus
from easy_breezy.core.events import EventBus
from easy_breezy.core.holds import HoldManager
from easy_breezy.core.pairing import (
    BlePairingService,
    FakePairingService,
    PairingService,
)
from easy_breezy.core.registry import DeviceRegistry
from easy_breezy.core.state import StateCache
from easy_breezy.core.telemetry import TelemetryService
from easy_breezy.integrations.yandex.callbacks import YandexNotifier
from easy_breezy.storage import Database
from easy_breezy.storage.repos import DeviceRepo


@dataclass
class AppContainer:
    settings: Settings
    db: Database
    events: EventBus
    cache: StateCache
    holds: HoldManager
    registry: DeviceRegistry
    bus: CommandBus
    telemetry: TelemetryService
    auth: AuthService
    pairing: PairingService
    yandex_notifier: YandexNotifier
    ws_connections: set[Any] = field(default_factory=set)
    """Живые WebSocket-клиенты (для /api/system/stats)."""

    async def startup(self) -> None:
        """Порядок старта: миграции → журнал → dev-фейки → супервизоры."""
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        await self.db.migrate()
        await self.bus.start()
        if self.settings.fake_devices > 0:
            await seed_fake_devices(self.db, self.settings.fake_devices)
        await self.registry.start()
        await self.telemetry.start()
        await self.yandex_notifier.start()
        await self.auth.ensure_setup_token()

    async def shutdown(self) -> None:
        await self.yandex_notifier.stop()
        await self.telemetry.stop()
        await self.bus.stop()
        await self.registry.stop()
        await self.db.dispose()


def build_container(settings: Settings) -> AppContainer:
    db = Database(settings.resolved_database_url())
    events = EventBus()
    cache = StateCache()
    holds = HoldManager(duration_seconds=settings.manual_hold_minutes * 60)
    scan_gate = asyncio.Lock()
    transport_factory = make_transport_factory(settings)
    registry = DeviceRegistry(db, events, cache, transport_factory, scan_gate=scan_gate)
    bus = CommandBus(db, registry, events, holds)
    telemetry = TelemetryService(db, events)
    auth = AuthService(db, session_ttl_seconds=settings.session_ttl_days * 86400)
    pairing: PairingService
    if settings.fake_devices > 0:
        pairing = FakePairingService(db, registry, events, seeded=settings.fake_devices)
    else:
        pairing = BlePairingService(
            db, registry, events, transport_factory, scan_gate=scan_gate
        )
    yandex_notifier = YandexNotifier(
        db,
        events,
        cache,
        registry,
        skill_id=settings.yandex_skill_id,
        callback_token=settings.yandex_callback_token,
    )
    return AppContainer(
        settings=settings,
        db=db,
        events=events,
        cache=cache,
        holds=holds,
        registry=registry,
        bus=bus,
        telemetry=telemetry,
        auth=auth,
        pairing=pairing,
        yandex_notifier=yandex_notifier,
    )


def make_transport_factory(settings: Settings) -> Callable[[str], BleTransport]:
    """Фабрика транспортов: bleak для железа, FakeS4 в dev-режиме.

    В dev-режиме эмулятор на MAC один и живёт всё время процесса — состояние
    переживает переподключения, как у настоящего бризера.
    """
    if settings.fake_devices > 0:
        emulators: dict[str, FakeS4Device] = {}

        def fake_factory(mac: str) -> BleTransport:
            return FakeTransport(emulators.setdefault(mac, FakeS4Device()), address=mac)

        return fake_factory

    def bleak_factory(mac: str) -> BleTransport:
        return BleakTransport(mac, notify_uuid=GATT_NOTIFY, write_uuid=GATT_WRITE)

    return bleak_factory


async def seed_fake_devices(db: Database, count: int) -> None:
    """Dev-режим EB_FAKE_DEVICES=N: регистрирует фейки идемпотентно по MAC."""
    now = int(time.time())
    async with db.session() as session:
        repo = DeviceRepo(session)
        for index in range(1, count + 1):
            mac = fake_mac(index)
            device = await repo.get_by_mac(mac)
            if device is None:
                await repo.create(
                    mac=mac,
                    name=f"Фейковый бризер {index}",
                    created_at=now,
                    paired=True,
                )
            elif device.deleted_at is not None:  # вернуть удалённый фейк
                device.deleted_at = None
                device.paired = True
