"""Журнал команд: чтение истории и конкретного итога."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from easy_breezy.api.deps import ContainerDep, require_user
from easy_breezy.api.schemas import CommandView
from easy_breezy.storage.repos import CommandRepo

router = APIRouter(
    prefix="/api/commands", tags=["commands"], dependencies=[Depends(require_user)]
)


@router.get("")
async def list_commands(
    container: ContainerDep,
    device_uuid: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[CommandView]:
    async with container.db.session() as session:
        repo = CommandRepo(session)
        records = (
            await repo.list_for_device(device_uuid, limit=limit)
            if device_uuid is not None
            else await repo.list_recent(limit=limit)
        )
    return [CommandView.from_record(record) for record in records]


@router.get("/{command_id}")
async def get_command(command_id: int, container: ContainerDep) -> CommandView:
    async with container.db.session() as session:
        record = await CommandRepo(session).get(command_id)
    if record is None:
        raise HTTPException(status_code=404, detail="команда не найдена")
    return CommandView.from_record(record)
