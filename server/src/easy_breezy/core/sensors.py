"""Реестр датчиков и приём измерений (план §10, FR-25/26/27).

Единая точка входа для MagicAir-опроса и MQTT-инжеста: обновляет
``last_values``/``last_seen_at`` в реестре и публикует ``sensor.updated`` —
дальше телеметрия пишет историю, триггеры оценивают условия, UI обновляется.

MagicAir-датчики регистрируются автоматически при первом появлении в облаке;
MQTT-датчики заводятся вручную в UI (чужие топики игнорируются).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Any

import structlog

from easy_breezy.core.events import (
    TOPIC_DEVICE_LIST_CHANGED,
    TOPIC_SENSOR_UPDATED,
    EventBus,
)
from easy_breezy.storage import Database
from easy_breezy.storage.repos import SensorRepo

log = structlog.get_logger(__name__)

STALE_AFTER_SECONDS = 300
"""Данные старше 5 минут считаются устаревшими (FR-25)."""

METRICS = ("co2", "temperature", "humidity")

KIND_MAGICAIR = "magicair"
KIND_MQTT = "mqtt"


def clean_metrics(raw: dict[str, Any]) -> dict[str, float]:
    """Известные метрики с конечными числовыми значениями (NaN отбрасывается)."""
    clean: dict[str, float] = {}
    for metric in METRICS:
        value = raw.get(metric)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        number = float(value)
        if math.isfinite(number):
            clean[metric] = number
    return clean


class SensorIngest:
    def __init__(
        self,
        db: Database,
        events: EventBus,
        *,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._db = db
        self._events = events
        self._now = now

    async def ingest(
        self,
        *,
        kind: str,
        source_key: str,
        metrics: dict[str, Any],
        name: str | None = None,
        auto_register: bool = False,
    ) -> int | None:
        """Принимает измерение; возвращает id датчика или None (проигнорировано)."""
        clean = clean_metrics(metrics)
        if not clean:
            log.debug("sensor_metrics_empty", source_key=source_key)
            return None
        ts = int(self._now())
        registered = False
        async with self._db.session() as session:
            repo = SensorRepo(session)
            sensor = await repo.get_by_source_key(source_key)
            if sensor is None:
                if not auto_register:
                    log.debug("sensor_unknown_source", source_key=source_key)
                    return None
                sensor = await repo.create(
                    kind=kind, name=name or source_key, source_key=source_key
                )
                registered = True
            # мерж: по-метричные MQTT-топики шлют метрики порознь, а реестр
            # держит полный последний срез; событие несёт только свежие
            sensor.last_values = {**(sensor.last_values or {}), **clean}
            sensor.last_seen_at = ts
            sensor_id = sensor.id
        if registered:
            log.info("sensor_registered", sensor_id=sensor_id, kind=kind, name=name)
            # список устройств Яндекса пополнился — discovery-callback
            self._events.publish(TOPIC_DEVICE_LIST_CHANGED, {"sensor_id": sensor_id})
        self._events.publish(
            TOPIC_SENSOR_UPDATED,
            {"sensor_id": sensor_id, "kind": kind, "metrics": clean, "ts": ts},
        )
        return sensor_id
