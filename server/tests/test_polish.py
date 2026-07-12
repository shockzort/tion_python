"""Фаза 9: бэкапы с восстановлением, watchdog-эскалация, push-надзор."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.events import (
    TOPIC_BACKUP_FAILED,
    TOPIC_BACKUP_FINISHED,
    EventBus,
)
from easy_breezy.core.push import PushService
from easy_breezy.core.watchdog import BleWatchdog
from easy_breezy.storage import Database
from easy_breezy.storage.backup import BackupError, BackupService, restore_archive
from easy_breezy.storage.repos import DeviceRepo
from easy_breezy.storage.repos.push import PushRepo
from tests.conftest import FakeClock

MSK = ZoneInfo("Europe/Moscow")
NOON = 1_783_846_800.0  # 2026-07-12 12:00 UTC-ish; точное значение не важно


# --- бэкапы -----------------------------------------------------------------


async def seed_device(db: Database) -> str:
    async with db.session() as session:
        device = await DeviceRepo(session).create(
            mac="FA:KE:00:00:00:01", name="Бризер", created_at=100, paired=True
        )
        return device.uuid


async def test_backup_and_restore_roundtrip(db: Database, tmp_path: Path) -> None:
    """Гейт фазы: восстановление снапшота на чистой БД (NFR-7)."""
    device_uuid = await seed_device(db)
    events = EventBus()
    service = BackupService(db, events, tmp_path, FakeClock(NOON), tz=MSK)

    with events.subscribe(TOPIC_BACKUP_FINISHED) as subscription:
        archive = await service.run_backup()
        event = await asyncio.wait_for(subscription.get(), 1)
    assert archive.exists()
    assert event.data["archive"] == archive.name
    assert event.data["size"] > 0

    # восстановление в «чистую» БД: файл на месте, данные читаются
    restored = tmp_path / "restored.db"
    restore_archive(archive, restored)
    with sqlite3.connect(restored) as connection:
        rows = connection.execute("SELECT uuid, name FROM devices").fetchall()
    assert rows == [(device_uuid, "Бризер")]


async def test_backup_retention_keeps_last_seven(
    db: Database, tmp_path: Path
) -> None:
    events = EventBus()
    clock = FakeClock(NOON)
    service = BackupService(db, events, tmp_path, clock, tz=MSK)
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    for index in range(9):  # девять старых архивов
        (backups_dir / f"easy_breezy-2026010{index}-000000.db.gz").write_bytes(b"x")

    await service.run_backup()
    remaining = sorted(p.name for p in backups_dir.glob("*.db.gz"))
    assert len(remaining) == 7
    # выжили самые свежие: 3..8 из старых + новый
    assert remaining[0] == "easy_breezy-20260103-000000.db.gz"


async def test_backup_failure_publishes_event(db: Database, tmp_path: Path) -> None:
    events = EventBus()
    occupied = tmp_path / "occupied"
    occupied.write_text("не каталог")  # mkdir(backups) внутри файла упадёт
    service = BackupService(
        db, events, occupied / "sub", FakeClock(NOON), tz=MSK
    )
    with events.subscribe(TOPIC_BACKUP_FAILED) as subscription:
        with pytest.raises(BackupError):
            await service.run_backup()
        event = await asyncio.wait_for(subscription.get(), 1)
    assert "error" in event.data


def test_backup_next_run_at_0330_local() -> None:
    from datetime import datetime

    events = EventBus()
    service = BackupService(
        Database("sqlite+aiosqlite://"), events, Path("/tmp"), FakeClock(0), tz=MSK
    )
    morning = datetime(2026, 7, 12, 2, 0, tzinfo=MSK).timestamp()
    run_at = datetime.fromtimestamp(service.next_run(morning), MSK)
    assert (run_at.hour, run_at.minute) == (3, 30)
    assert run_at.day == 12  # сегодня, ещё не проехали
    evening = datetime(2026, 7, 12, 22, 0, tzinfo=MSK).timestamp()
    run_at = datetime.fromtimestamp(service.next_run(evening), MSK)
    assert run_at.day == 13  # уже завтра


# --- watchdog ----------------------------------------------------------------


class WatchdogHarness:
    def __init__(self, clock: FakeClock) -> None:
        self.connections: dict[str, ConnectionState] = {}
        self.resets = 0
        self.terminated = False
        self.pings: list[str] = []

        async def reset() -> bool:
            self.resets += 1
            return True

        self.watchdog = BleWatchdog(
            lambda: dict(self.connections),
            clock,
            adapter_reset=reset,
            terminate=lambda: setattr(self, "terminated", True),
            notify=lambda state: self.pings.append(state) or True,
        )


async def test_watchdog_escalates_reset_then_restart() -> None:
    clock = FakeClock(NOON)
    harness = WatchdogHarness(clock)
    harness.connections = {
        "a": ConnectionState.CONNECTING,
        "b": ConnectionState.DISCONNECTED,
    }
    await harness.watchdog.check_once()  # фиксация начала эпизода
    clock._now += 601
    await harness.watchdog.check_once()  # 10 минут — сброс адаптера
    assert harness.resets == 1
    assert not harness.terminated

    clock._now += 599
    await harness.watchdog.check_once()  # свежий грейс после сброса ещё идёт
    assert not harness.terminated
    clock._now += 2
    await harness.watchdog.check_once()  # и он истёк — рестарт сервиса
    assert harness.terminated
    assert harness.resets == 1


async def test_watchdog_resets_on_recovery_and_ignores_empty() -> None:
    clock = FakeClock(NOON)
    harness = WatchdogHarness(clock)

    await harness.watchdog.check_once()  # пустой реестр — не эпизод
    harness.connections = {"a": ConnectionState.DISCONNECTED}
    await harness.watchdog.check_once()
    clock._now += 601
    await harness.watchdog.check_once()
    assert harness.resets == 1

    harness.connections["a"] = ConnectionState.ONLINE  # вернулся
    await harness.watchdog.check_once()
    harness.connections["a"] = ConnectionState.DISCONNECTED
    await harness.watchdog.check_once()
    clock._now += 601
    await harness.watchdog.check_once()
    assert harness.resets == 2  # новый эпизод — новая эскалация с нуля
    assert not harness.terminated


# --- push ---------------------------------------------------------------------


class PushHarness(PushService):
    """PushService с перехваченной отправкой (без сети и ключей)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.sent: list[tuple[str, str]] = []

    async def send_to_all(self, title: str, body: str) -> int:
        self.sent.append((title, body))
        return 1


async def test_push_offline_notifies_once_per_episode(db: Database) -> None:
    device_uuid = await seed_device(db)
    events = EventBus()
    clock = FakeClock(NOON)
    connections = {device_uuid: ConnectionState.DISCONNECTED}
    push = PushHarness(
        db,
        events,
        lambda: dict(connections),
        Path("/nonexistent"),
        clock,
        contact="https://example.com",
    )

    await push.check_offline_once()  # эпизод начался
    clock._now += 601
    await push.check_offline_once()  # 10 минут — уведомление
    assert len(push.sent) == 1
    assert "Бризер" in push.sent[0][1]

    clock._now += 3600
    await push.check_offline_once()  # тот же эпизод — без спама
    assert len(push.sent) == 1

    connections[device_uuid] = ConnectionState.ONLINE
    await push.check_offline_once()
    connections[device_uuid] = ConnectionState.DISCONNECTED
    await push.check_offline_once()
    clock._now += 601
    await push.check_offline_once()  # новый эпизод — новое уведомление
    assert len(push.sent) == 2


async def test_push_backup_failed_event_notifies(db: Database) -> None:
    events = EventBus()
    push = PushHarness(
        db,
        events,
        dict,
        Path("/nonexistent"),
        FakeClock(NOON),
        contact="https://example.com",
    )
    push._vapid = object()  # type: ignore[assignment] — send перехвачен
    subscription = events.subscribe(TOPIC_BACKUP_FAILED)
    task = asyncio.create_task(push._watch_events(subscription))
    try:
        events.publish(TOPIC_BACKUP_FAILED, {"error": "диск переполнен"})
        for _ in range(100):
            if push.sent:
                break
            await asyncio.sleep(0.01)
        assert push.sent == [("Провал бэкапа", "Снапшот БД не создан: диск переполнен")]
    finally:
        task.cancel()
        subscription.close()


async def test_push_subscription_lifecycle(db: Database, tmp_path: Path) -> None:
    """VAPID-ключи генерируются, подписка живёт в БД, отписка удаляет."""
    events = EventBus()
    push = PushService(
        db,
        events,
        dict,
        tmp_path,
        FakeClock(NOON),
        contact="https://example.com",
    )
    await push.start()
    try:
        assert len(push.public_key) > 40  # base64url несжатой точки P-256
        assert (tmp_path / "vapid_private.pem").exists()

        await push.subscribe(
            endpoint="https://push.example/sub1", keys={"p256dh": "k", "auth": "a"}
        )
        await push.subscribe(  # повтор того же endpoint — upsert, не дубль
            endpoint="https://push.example/sub1", keys={"p256dh": "k2", "auth": "a2"}
        )
        async with db.session() as session:
            subscriptions = await PushRepo(session).list_all()
        assert len(subscriptions) == 1
        assert subscriptions[0].keys["p256dh"] == "k2"

        assert await push.unsubscribe("https://push.example/sub1")
        assert not await push.unsubscribe("https://push.example/sub1")
    finally:
        await push.stop()
