"""Выборка телеметрии для графиков (FR-29): сырьё и часовые агрегаты."""

from __future__ import annotations

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from easy_breezy.api.deps import ContainerDep, require_user
from easy_breezy.storage.repos import TelemetryRepo

router = APIRouter(
    prefix="/api", tags=["telemetry"], dependencies=[Depends(require_user)]
)

_MAX_RANGE_SECONDS = 2 * 366 * 86400  # глубже ретенции агрегатов смысла нет


class RawPoint(BaseModel):
    ts: int
    value: float


class HourlyPoint(BaseModel):
    ts: int
    min: float
    max: float
    avg: float


class TelemetrySeries(BaseModel):
    source_type: str
    source_id: str
    metric: str
    agg: str
    raw: list[RawPoint] | None = None
    hourly: list[HourlyPoint] | None = None


@router.get("/telemetry")
async def get_telemetry(
    container: ContainerDep,
    source_id: str,
    metric: str,
    source_type: Literal["device", "sensor"] = "device",
    agg: Literal["raw", "hourly"] = "raw",
    from_ts: int | None = Query(default=None, ge=0),
    to_ts: int | None = Query(default=None, ge=0),
) -> TelemetrySeries:
    """Серия метрики за интервал; по умолчанию — последние сутки сырья."""
    now = int(time.time())
    resolved_to = to_ts if to_ts is not None else now
    resolved_from = from_ts if from_ts is not None else resolved_to - 86400
    if resolved_from >= resolved_to:
        raise HTTPException(status_code=422, detail="from_ts должен быть меньше to_ts")
    if resolved_to - resolved_from > _MAX_RANGE_SECONDS:
        raise HTTPException(status_code=422, detail="интервал слишком велик")

    series = TelemetrySeries(
        source_type=source_type, source_id=source_id, metric=metric, agg=agg
    )
    async with container.db.session() as session:
        repo = TelemetryRepo(session)
        if agg == "raw":
            points = await repo.select_raw(
                source_type=source_type,
                source_id=source_id,
                metric=metric,
                from_ts=resolved_from,
                to_ts=resolved_to,
            )
            series.raw = [RawPoint(ts=ts, value=value) for ts, value in points]
        else:
            hours = await repo.select_hourly(
                source_type=source_type,
                source_id=source_id,
                metric=metric,
                from_ts=resolved_from,
                to_ts=resolved_to,
            )
            series.hourly = [
                HourlyPoint(ts=hour, min=v_min, max=v_max, avg=v_avg)
                for hour, v_min, v_max, v_avg in hours
            ]
    return series
