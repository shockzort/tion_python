"""Телеметрия: запись метрик по событиям, ежечасный downsample, ретенции."""

from __future__ import annotations

import asyncio

from sqlalchemy import select

from easy_breezy.ble.fake import DEFAULT_STATE
from easy_breezy.core.events import TOPIC_STATE_CHANGED, EventBus
from easy_breezy.core.model import state_to_dict
from easy_breezy.core.telemetry import (
    HOUR,
    TelemetryService,
    seconds_until_maintenance,
)
from easy_breezy.storage import Database
from easy_breezy.storage.models import TelemetryHourly, TelemetryRaw
from easy_breezy.storage.repos import TelemetryPoint, TelemetryRepo


class FakeNow:
    def __init__(self, value: float) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


async def fetch_raw(db: Database) -> list[TelemetryRaw]:
    async with db.session() as session:
        result = await session.execute(select(TelemetryRaw))
        return list(result.scalars())


async def test_recorder_writes_device_metrics(db: Database) -> None:
    events = EventBus()
    now = FakeNow(10 * HOUR + 5)
    service = TelemetryService(db, events, now=now)
    await service.start()
    try:
        events.publish(
            TOPIC_STATE_CHANGED,
            {"device_uuid": "dev-1", "state": state_to_dict(DEFAULT_STATE)},
        )
        rows: list[TelemetryRaw] = []
        for _ in range(300):  # рекордер асинхронный — ждём все 6 метрик
            rows = await fetch_raw(db)
            if len(rows) == 6:
                break
            await asyncio.sleep(0.01)

        metrics = {row.metric: row.value for row in rows}
        assert metrics == {
            "in_temp": 5.0,
            "out_temp": 18.0,
            "fan_speed": 2.0,
            "heater_temp": 20.0,
            "heater": 0.0,
            "filter_days": 180.0,
        }
        assert all(row.ts == int(now.value) for row in rows)
        assert all(
            (row.source_type, row.source_id) == ("device", "dev-1") for row in rows
        )
    finally:
        await service.stop()


async def test_maintenance_aggregates_pending_hours_and_purges(db: Database) -> None:
    now = FakeNow(float(100 * HOUR + 120))  # 100-й час, две минуты внутрь
    service = TelemetryService(db, EventBus(), now=now)

    async with db.session() as session:
        repo = TelemetryRepo(session)
        # два завершённых часа (98-й и 99-й) + точка текущего (100-го)
        await repo.add_points(
            [
                TelemetryPoint(98 * HOUR + 10, "device", "d1", "fan_speed", 2.0),
                TelemetryPoint(98 * HOUR + 20, "device", "d1", "fan_speed", 4.0),
                TelemetryPoint(99 * HOUR + 30, "device", "d1", "fan_speed", 6.0),
                TelemetryPoint(100 * HOUR + 60, "device", "d1", "fan_speed", 1.0),
            ]
        )

    await service.run_maintenance()

    async with db.session() as session:
        result = await session.execute(
            select(TelemetryHourly).order_by(TelemetryHourly.hour_ts)
        )
        hourly = list(result.scalars())
    assert [row.hour_ts for row in hourly] == [98 * HOUR, 99 * HOUR]
    first = hourly[0]
    assert (first.value_min, first.value_max, first.samples) == (2.0, 4.0, 2)
    assert first.value_avg == 3.0

    # повторный запуск ничего не дублирует (идемпотентность)
    await service.run_maintenance()
    async with db.session() as session:
        result = await session.execute(select(TelemetryHourly))
        assert len(list(result.scalars())) == 2

    # ретенция: сырые точки старше 7 дней удаляются
    now.value = float(98 * HOUR + 8 * 86400)
    await service.run_maintenance()
    assert await fetch_raw(db) == []


def test_seconds_until_maintenance() -> None:
    assert seconds_until_maintenance(10 * HOUR) == 60  # ровно на границе часа
    assert seconds_until_maintenance(10 * HOUR + 30) == 30  # offset ещё не прошёл
    assert seconds_until_maintenance(10 * HOUR + 60) == HOUR  # ровно в offset
    assert seconds_until_maintenance(10 * HOUR + 1800) == 1860  # середина часа
