"""Репозиторий телеметрии: сырые точки, часовые агрегаты, ретенции."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import TelemetryHourly, TelemetryRaw
from easy_breezy.storage.repos._util import rowcount

HOUR = 3600


@dataclass(frozen=True, slots=True)
class TelemetryPoint:
    ts: int
    source_type: str
    source_id: str
    metric: str
    value: float


class TelemetryRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_points(self, points: Iterable[TelemetryPoint]) -> None:
        self._session.add_all(
            TelemetryRaw(
                ts=p.ts,
                source_type=p.source_type,
                source_id=p.source_id,
                metric=p.metric,
                value=p.value,
            )
            for p in points
        )
        await self._session.flush()

    async def downsample_hour(self, hour_start: int) -> int:
        """Агрегирует сырые точки часа в ``telemetry_hourly`` (идемпотентно).

        Возвращает число получившихся серий; повторный вызов за тот же час
        перезаписывает агрегаты (час пересчитывается целиком).
        """
        await self._session.execute(
            delete(TelemetryHourly).where(TelemetryHourly.hour_ts == hour_start)
        )
        result = await self._session.execute(
            select(
                TelemetryRaw.source_type,
                TelemetryRaw.source_id,
                TelemetryRaw.metric,
                func.min(TelemetryRaw.value),
                func.max(TelemetryRaw.value),
                func.avg(TelemetryRaw.value),
                func.count(TelemetryRaw.id),
            )
            .where(TelemetryRaw.ts >= hour_start, TelemetryRaw.ts < hour_start + HOUR)
            .group_by(
                TelemetryRaw.source_type, TelemetryRaw.source_id, TelemetryRaw.metric
            )
        )
        rows = result.all()
        self._session.add_all(
            TelemetryHourly(
                hour_ts=hour_start,
                source_type=source_type,
                source_id=source_id,
                metric=metric,
                value_min=v_min,
                value_max=v_max,
                value_avg=v_avg,
                samples=samples,
            )
            for source_type, source_id, metric, v_min, v_max, v_avg, samples in rows
        )
        await self._session.flush()
        return len(rows)

    async def purge(self, *, raw_before: int, hourly_before: int) -> tuple[int, int]:
        """Ретенции плана §5: raw — 7 дней, hourly — 2 года."""
        raw = await self._session.execute(
            delete(TelemetryRaw).where(TelemetryRaw.ts < raw_before)
        )
        hourly = await self._session.execute(
            delete(TelemetryHourly).where(TelemetryHourly.hour_ts < hourly_before)
        )
        return rowcount(raw), rowcount(hourly)
