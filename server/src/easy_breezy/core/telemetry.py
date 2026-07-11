"""Телеметрия: рекордер событий состояния + ежечасное обслуживание (план §10).

Рекордер пишет метрики устройств из ``device.state_changed`` и метрики
датчиков из ``sensor.updated`` в ``telemetry_raw``; обслуживание раз в час
агрегирует завершённые часы в ``telemetry_hourly`` (с догоном пропущенных
после простоя — raw живёт 7 дней) и применяет ретенции.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from easy_breezy.core.events import (
    TOPIC_SENSOR_UPDATED,
    TOPIC_STATE_CHANGED,
    Event,
    EventBus,
    Subscription,
)
from easy_breezy.storage import Database
from easy_breezy.storage.repos import TelemetryPoint, TelemetryRepo

log = structlog.get_logger(__name__)

HOUR = 3600
RAW_RETENTION_SECONDS = 7 * 86400
HOURLY_RETENTION_SECONDS = 2 * 365 * 86400


def seconds_until_maintenance(now: float, *, offset: float = 60.0) -> float:
    """Пауза до следующего запуска: начало часа + offset (час уже завершён)."""
    into_hour = now % HOUR
    if into_hour < offset:
        return offset - into_hour
    return HOUR - into_hour + offset


def _device_metrics(state: dict[str, Any]) -> dict[str, float]:
    return {
        "in_temp": float(state["in_temp"]),
        "out_temp": float(state["out_temp"]),
        "fan_speed": float(state["fan_speed"]),
        "heater_temp": float(state["heater_temp"]),
        "heater": 1.0 if state["heater"] else 0.0,
        "filter_days": float(state["filter_remain_days"]),
    }


class TelemetryService:
    def __init__(
        self,
        db: Database,
        events: EventBus,
        *,
        now: Callable[[], float] = time.time,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._db = db
        self._events = events
        self._now = now
        self._sleep = sleep
        self._tasks: list[asyncio.Task[None]] = []
        self._subscription: Subscription | None = None

    async def start(self) -> None:
        # подписка синхронно — события между start() и запуском задачи не теряются
        self._subscription = self._events.subscribe(
            TOPIC_STATE_CHANGED, TOPIC_SENSOR_UPDATED
        )
        self._tasks = [
            asyncio.create_task(
                self._record_loop(self._subscription), name="telemetry-recorder"
            ),
            asyncio.create_task(self._maintenance_loop(), name="telemetry-hourly"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        if self._subscription is not None:
            self._subscription.close()
            self._subscription = None

    async def _record_loop(self, subscription: Subscription) -> None:
        async for event in subscription:
            try:
                await self._record(event)
            except Exception:
                # телеметрия не должна умирать от одного сбоя записи
                log.exception("telemetry_record_failed")

    async def _record(self, event: Event) -> None:
        if event.topic == TOPIC_SENSOR_UPDATED:
            source_type = "sensor"
            source_id = str(event.data["sensor_id"])
            metrics: dict[str, float] = event.data["metrics"]
        else:
            source_type = "device"
            source_id = event.data["device_uuid"]
            metrics = _device_metrics(event.data["state"])
        ts = int(self._now())
        async with self._db.session() as session:
            await TelemetryRepo(session).add_points(
                TelemetryPoint(ts, source_type, source_id, metric, value)
                for metric, value in metrics.items()
            )

    async def _maintenance_loop(self) -> None:
        while True:
            await self._sleep(seconds_until_maintenance(self._now()))
            try:
                await self.run_maintenance()
            except Exception:
                log.exception("telemetry_maintenance_failed")

    async def run_maintenance(self) -> None:
        """Агрегирует завершённые часы и применяет ретенции (идемпотентно)."""
        now = int(self._now())
        current_hour = now // HOUR * HOUR
        async with self._db.session() as session:
            repo = TelemetryRepo(session)
            pending = await repo.hours_pending(before=current_hour)
            for hour_start in pending:
                series = await repo.downsample_hour(hour_start)
                log.debug("telemetry_hour_aggregated", hour=hour_start, series=series)
            purged_raw, purged_hourly = await repo.purge(
                raw_before=now - RAW_RETENTION_SECONDS,
                hourly_before=now - HOURLY_RETENTION_SECONDS,
            )
        if pending or purged_raw or purged_hourly:
            log.info(
                "telemetry_maintenance",
                hours=len(pending),
                purged_raw=purged_raw,
                purged_hourly=purged_hourly,
            )
