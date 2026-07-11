"""Репозитории автоматизации: сценарии и расписания."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import Scenario, Schedule


class ScenarioRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, name: str, actions: list[Any]) -> Scenario:
        scenario = Scenario(name=name, actions=actions)
        self._session.add(scenario)
        await self._session.flush()
        return scenario

    async def get(self, scenario_id: int) -> Scenario | None:
        return await self._session.get(Scenario, scenario_id)

    async def list_all(self) -> list[Scenario]:
        result = await self._session.execute(select(Scenario).order_by(Scenario.name))
        return list(result.scalars())

    async def delete(self, scenario: Scenario) -> None:
        await self._session.delete(scenario)


class ScheduleRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        name: str,
        cron: str,
        scenario_id: int | None,
        actions: list[Any] | None,
        enabled: bool,
    ) -> Schedule:
        schedule = Schedule(
            name=name,
            cron=cron,
            scenario_id=scenario_id,
            actions=actions,
            enabled=enabled,
        )
        self._session.add(schedule)
        await self._session.flush()
        return schedule

    async def get(self, schedule_id: int) -> Schedule | None:
        return await self._session.get(Schedule, schedule_id)

    async def list_all(self) -> list[Schedule]:
        result = await self._session.execute(select(Schedule).order_by(Schedule.name))
        return list(result.scalars())

    async def list_enabled(self) -> list[Schedule]:
        result = await self._session.execute(
            select(Schedule).where(Schedule.enabled).order_by(Schedule.id)
        )
        return list(result.scalars())

    async def delete(self, schedule: Schedule) -> None:
        await self._session.delete(schedule)
