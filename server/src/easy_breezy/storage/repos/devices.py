"""Репозитории устройств и комнат."""

from __future__ import annotations

import uuid as uuid_module

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import Device, Room


class DeviceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        mac: str,
        name: str,
        created_at: int,
        model: str = "s4",
        paired: bool = False,
        room_id: int | None = None,
    ) -> Device:
        device = Device(
            uuid=uuid_module.uuid4().hex,
            mac=mac.upper(),
            name=name,
            model=model,
            paired=paired,
            room_id=room_id,
            created_at=created_at,
        )
        self._session.add(device)
        await self._session.flush()
        return device

    async def get(self, uuid: str) -> Device | None:
        return await self._session.get(Device, uuid)

    async def get_by_mac(self, mac: str) -> Device | None:
        result = await self._session.execute(
            select(Device).where(Device.mac == mac.upper())
        )
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Device]:
        result = await self._session.execute(
            select(Device).where(Device.deleted_at.is_(None)).order_by(Device.name)
        )
        return list(result.scalars())

    async def soft_delete(self, device: Device, *, deleted_at: int) -> None:
        device.deleted_at = deleted_at
        device.paired = False


class RoomRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, name: str) -> Room:
        room = Room(name=name)
        self._session.add(room)
        await self._session.flush()
        return room

    async def get(self, room_id: int) -> Room | None:
        return await self._session.get(Room, room_id)

    async def list_all(self) -> list[Room]:
        result = await self._session.execute(select(Room).order_by(Room.name))
        return list(result.scalars())

    async def delete(self, room: Room) -> None:
        await self._session.delete(room)
