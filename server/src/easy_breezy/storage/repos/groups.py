"""Репозиторий групп устройств (join-таблица участников)."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import DeviceGroup, DeviceGroupMember


class GroupRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, name: str) -> DeviceGroup:
        group = DeviceGroup(name=name)
        self._session.add(group)
        await self._session.flush()
        return group

    async def get(self, group_id: int) -> DeviceGroup | None:
        return await self._session.get(DeviceGroup, group_id)

    async def list_all(self) -> list[DeviceGroup]:
        result = await self._session.execute(
            select(DeviceGroup).order_by(DeviceGroup.name)
        )
        return list(result.scalars())

    async def delete(self, group: DeviceGroup) -> None:
        await self._session.delete(group)

    async def members(self, group_id: int) -> list[str]:
        result = await self._session.execute(
            select(DeviceGroupMember.device_uuid).where(
                DeviceGroupMember.group_id == group_id
            )
        )
        return list(result.scalars())

    async def set_members(self, group_id: int, device_uuids: list[str]) -> None:
        """Полная замена состава группы."""
        await self._session.execute(
            delete(DeviceGroupMember).where(DeviceGroupMember.group_id == group_id)
        )
        self._session.add_all(
            DeviceGroupMember(group_id=group_id, device_uuid=uuid)
            for uuid in device_uuids
        )
        await self._session.flush()
