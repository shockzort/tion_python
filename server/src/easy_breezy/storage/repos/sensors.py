"""Репозитории датчиков и триггеров."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import Sensor, Trigger


class SensorRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, kind: str, name: str, source_key: str) -> Sensor:
        sensor = Sensor(kind=kind, name=name, source_key=source_key)
        self._session.add(sensor)
        await self._session.flush()
        return sensor

    async def get(self, sensor_id: int) -> Sensor | None:
        return await self._session.get(Sensor, sensor_id)

    async def get_by_source_key(self, source_key: str) -> Sensor | None:
        result = await self._session.execute(
            select(Sensor).where(Sensor.source_key == source_key)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Sensor]:
        result = await self._session.execute(select(Sensor).order_by(Sensor.name))
        return list(result.scalars())

    async def delete(self, sensor: Sensor) -> None:
        await self._session.delete(sensor)


class TriggerRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, **fields: Any) -> Trigger:
        trigger = Trigger(**fields)
        self._session.add(trigger)
        await self._session.flush()
        return trigger

    async def get(self, trigger_id: int) -> Trigger | None:
        return await self._session.get(Trigger, trigger_id)

    async def list_all(self) -> list[Trigger]:
        result = await self._session.execute(select(Trigger).order_by(Trigger.name))
        return list(result.scalars())

    async def list_enabled_for_sensor(self, sensor_id: int) -> list[Trigger]:
        result = await self._session.execute(
            select(Trigger)
            .where(Trigger.enabled, Trigger.sensor_id == sensor_id)
            .order_by(Trigger.id)
        )
        return list(result.scalars())

    async def delete(self, trigger: Trigger) -> None:
        await self._session.delete(trigger)
