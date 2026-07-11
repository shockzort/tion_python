"""Устройства и комнаты: CRUD, команды, manual-hold."""

from __future__ import annotations

import asyncio
import uuid as uuid_module

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from easy_breezy.api.deps import ContainerDep, require_user
from easy_breezy.api.schemas import (
    CommandBody,
    CommandResult,
    DeviceCreate,
    DeviceUpdate,
    DeviceView,
)
from easy_breezy.container import AppContainer
from easy_breezy.core.bus import CommandError, CommandTicket
from easy_breezy.core.model import state_to_dict
from easy_breezy.storage.models import CommandSource, Device
from easy_breezy.storage.repos import DeviceRepo, RoomRepo

router = APIRouter(
    prefix="/api", tags=["devices"], dependencies=[Depends(require_user)]
)


def build_device_view(device: Device, container: AppContainer) -> DeviceView:
    snapshot = container.cache.get(device.uuid)
    return DeviceView.build(
        device,
        connection=container.registry.connection(device.uuid).value,
        state=(
            state_to_dict(snapshot.state)
            if snapshot is not None and snapshot.state is not None
            else None
        ),
        state_at=snapshot.state_at if snapshot is not None else None,
        hold_until=container.holds.hold_until(device.uuid),
    )


async def get_active_device(device_uuid: str, container: AppContainer) -> Device:
    async with container.db.session() as session:
        device = await DeviceRepo(session).get(device_uuid)
    if device is None or device.deleted_at is not None:
        raise HTTPException(status_code=404, detail="устройство не найдено")
    return device


async def wait_outcome(container: AppContainer, ticket: CommandTicket) -> CommandResult:
    """Ждёт итог ограниченное время; не дождались — status=pending (финал по WS)."""
    try:
        outcome = await asyncio.wait_for(
            asyncio.shield(ticket.outcome),
            container.settings.command_wait_seconds,
        )
    except TimeoutError:
        return CommandResult(command_id=ticket.command_id, status="pending")
    return CommandResult.from_outcome(outcome)


@router.get("/devices")
async def list_devices(container: ContainerDep) -> list[DeviceView]:
    async with container.db.session() as session:
        devices = await DeviceRepo(session).list_active()
    return [build_device_view(device, container) for device in devices]


@router.post("/devices", status_code=201)
async def add_device(body: DeviceCreate, container: ContainerDep) -> DeviceView:
    """Регистрирует уже сопряжённый бризер (мастер сопряжения — Фаза 3)."""
    try:
        device = await container.registry.add_device(mac=body.mac, name=body.name)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="устройство с таким MAC уже есть"
        ) from exc
    return build_device_view(device, container)


@router.get("/devices/{device_uuid}")
async def get_device(device_uuid: str, container: ContainerDep) -> DeviceView:
    device = await get_active_device(device_uuid, container)
    return build_device_view(device, container)


@router.patch("/devices/{device_uuid}")
async def update_device(
    device_uuid: str, body: DeviceUpdate, container: ContainerDep
) -> DeviceView:
    await get_active_device(device_uuid, container)
    async with container.db.session() as session:
        device = await DeviceRepo(session).get(device_uuid)
        assert device is not None  # проверено выше, та же БД
        if body.name is not None:
            device.name = body.name
        if body.room_id is not None:
            if await RoomRepo(session).get(body.room_id) is None:
                raise HTTPException(status_code=404, detail="комната не найдена")
            device.room_id = body.room_id
    refreshed = await get_active_device(device_uuid, container)
    return build_device_view(refreshed, container)


@router.delete("/devices/{device_uuid}", status_code=204)
async def remove_device(device_uuid: str, container: ContainerDep) -> None:
    if not await container.registry.remove_device(device_uuid):
        raise HTTPException(status_code=404, detail="устройство не найдено")


@router.post("/devices/{device_uuid}/command")
async def submit_command(
    device_uuid: str,
    body: CommandBody,
    response: Response,
    container: ContainerDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> CommandResult:
    device = await get_active_device(device_uuid, container)
    key = idempotency_key or f"ui:{uuid_module.uuid4().hex}"
    try:
        ticket = await container.bus.submit(
            device_uuid=device.uuid,
            delta=body.to_delta(),
            source=CommandSource.UI,
            idempotency_key=key,
        )
    except CommandError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    result = await wait_outcome(container, ticket)
    if result.status == "pending":
        response.status_code = 202
    return result


@router.delete("/devices/{device_uuid}/hold", status_code=204)
async def release_hold(device_uuid: str, container: ContainerDep) -> None:
    """Кнопка «вернуть автоматику» (ADR-0005)."""
    await get_active_device(device_uuid, container)
    container.holds.release(device_uuid)


# --- комнаты -------------------------------------------------------------


class RoomView(BaseModel):
    id: int
    name: str


class RoomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


@router.get("/rooms")
async def list_rooms(container: ContainerDep) -> list[RoomView]:
    async with container.db.session() as session:
        rooms = await RoomRepo(session).list_all()
    return [RoomView(id=room.id, name=room.name) for room in rooms]


@router.post("/rooms", status_code=201)
async def add_room(body: RoomCreate, container: ContainerDep) -> RoomView:
    try:
        async with container.db.session() as session:
            room = await RoomRepo(session).create(body.name)
            view = RoomView(id=room.id, name=room.name)
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="комната с таким именем уже есть"
        ) from exc
    return view


@router.delete("/rooms/{room_id}", status_code=204)
async def remove_room(room_id: int, container: ContainerDep) -> None:
    async with container.db.session() as session:
        repo = RoomRepo(session)
        room = await repo.get(room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="комната не найдена")
        await repo.delete(room)
