"""Группы устройств: CRUD, состав, веерная команда (план §8)."""

from __future__ import annotations

import asyncio
import uuid as uuid_module

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from easy_breezy.api.deps import ContainerDep, require_user
from easy_breezy.api.rest.devices import wait_outcome
from easy_breezy.api.schemas import CommandBody, CommandResult, GroupCommandResult
from easy_breezy.container import AppContainer
from easy_breezy.core.bus import CommandError
from easy_breezy.storage.models import CommandSource, DeviceGroup
from easy_breezy.storage.repos import DeviceRepo, GroupRepo

router = APIRouter(
    prefix="/api/groups", tags=["groups"], dependencies=[Depends(require_user)]
)


class GroupView(BaseModel):
    id: int
    name: str
    device_uuids: list[str]


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class GroupMembers(BaseModel):
    device_uuids: list[str]


async def get_group(group_id: int, container: AppContainer) -> DeviceGroup:
    async with container.db.session() as session:
        group = await GroupRepo(session).get(group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="группа не найдена")
    return group


@router.get("")
async def list_groups(container: ContainerDep) -> list[GroupView]:
    async with container.db.session() as session:
        repo = GroupRepo(session)
        groups = await repo.list_all()
        return [
            GroupView(
                id=group.id, name=group.name, device_uuids=await repo.members(group.id)
            )
            for group in groups
        ]


@router.post("", status_code=201)
async def add_group(body: GroupCreate, container: ContainerDep) -> GroupView:
    try:
        async with container.db.session() as session:
            group = await GroupRepo(session).create(body.name)
            view = GroupView(id=group.id, name=group.name, device_uuids=[])
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409, detail="группа с таким именем уже есть"
        ) from exc
    return view


@router.put("/{group_id}/members")
async def set_members(
    group_id: int, body: GroupMembers, container: ContainerDep
) -> GroupView:
    group = await get_group(group_id, container)
    async with container.db.session() as session:
        devices = DeviceRepo(session)
        for device_uuid in body.device_uuids:
            device = await devices.get(device_uuid)
            if device is None or device.deleted_at is not None:
                raise HTTPException(
                    status_code=404, detail=f"устройство {device_uuid} не найдено"
                )
        repo = GroupRepo(session)
        await repo.set_members(group_id, body.device_uuids)
        members = await repo.members(group_id)
    return GroupView(id=group.id, name=group.name, device_uuids=members)


@router.delete("/{group_id}", status_code=204)
async def remove_group(group_id: int, container: ContainerDep) -> None:
    await get_group(group_id, container)
    async with container.db.session() as session:
        repo = GroupRepo(session)
        group = await repo.get(group_id)
        if group is not None:
            await repo.delete(group)


@router.post("/{group_id}/command")
async def submit_group_command(
    group_id: int,
    body: CommandBody,
    response: Response,
    container: ContainerDep,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> list[GroupCommandResult]:
    """Веер per-device команд; ответ — массив итогов (план §8)."""
    await get_group(group_id, container)
    async with container.db.session() as session:
        members = await GroupRepo(session).members(group_id)
    if not members:
        return []

    base_key = idempotency_key or f"ui:{uuid_module.uuid4().hex}"
    results: list[GroupCommandResult] = []
    waiters: list[tuple[str, asyncio.Task[CommandResult]]] = []
    for device_uuid in members:
        try:
            ticket = await container.bus.submit(
                device_uuid=device_uuid,
                delta=body.to_delta(),
                source=CommandSource.UI,
                idempotency_key=f"{base_key}:{device_uuid}",
            )
        except CommandError as exc:
            results.append(
                GroupCommandResult(device_uuid=device_uuid, rejected=str(exc))
            )
            continue
        # итоги ждём параллельно — общий дедлайн, а не сумма по устройствам
        waiters.append(
            (device_uuid, asyncio.create_task(wait_outcome(container, ticket)))
        )
    for device_uuid, waiter in waiters:
        results.append(GroupCommandResult(device_uuid=device_uuid, result=await waiter))
    if any(
        entry.result is not None and entry.result.status == "pending"
        for entry in results
    ):
        response.status_code = 202
    return results
