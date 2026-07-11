"""Репозиторий журнала команд (план §8)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import CommandRecord, CommandStatus
from easy_breezy.storage.repos._util import rowcount

_ACTIVE_STATUSES = (CommandStatus.PENDING.value, CommandStatus.RUNNING.value)


class CommandRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(
        self,
        *,
        idempotency_key: str,
        device_uuid: str,
        source: str,
        priority: int,
        payload: dict[str, Any],
        created_at: int,
    ) -> CommandRecord:
        record = CommandRecord(
            idempotency_key=idempotency_key,
            device_uuid=device_uuid,
            source=source,
            priority=priority,
            payload=payload,
            status=CommandStatus.PENDING,
            created_at=created_at,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def get(self, command_id: int) -> CommandRecord | None:
        return await self._session.get(CommandRecord, command_id)

    async def get_by_key(self, idempotency_key: str) -> CommandRecord | None:
        result = await self._session.execute(
            select(CommandRecord).where(
                CommandRecord.idempotency_key == idempotency_key
            )
        )
        return result.scalar_one_or_none()

    async def mark_running(self, command_id: int, *, started_at: int) -> None:
        await self._session.execute(
            update(CommandRecord)
            .where(CommandRecord.id == command_id)
            .values(status=CommandStatus.RUNNING, started_at=started_at)
        )

    async def finish(
        self,
        command_id: int,
        *,
        status: CommandStatus,
        finished_at: int,
        result_state: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        await self._session.execute(
            update(CommandRecord)
            .where(CommandRecord.id == command_id)
            .values(
                status=status,
                finished_at=finished_at,
                result_state=result_state,
                error=error,
            )
        )

    async def fail_interrupted(self, *, finished_at: int) -> int:
        """Помечает pending/running как failed — восстановление после рестарта."""
        result = await self._session.execute(
            update(CommandRecord)
            .where(CommandRecord.status.in_(_ACTIVE_STATUSES))
            .values(
                status=CommandStatus.FAILED,
                finished_at=finished_at,
                error="прерван рестартом сервиса",
            )
        )
        return rowcount(result)

    async def list_for_device(
        self, device_uuid: str, *, limit: int = 50
    ) -> list[CommandRecord]:
        result = await self._session.execute(
            select(CommandRecord)
            .where(CommandRecord.device_uuid == device_uuid)
            .order_by(CommandRecord.id.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def list_recent(self, *, limit: int = 50) -> list[CommandRecord]:
        result = await self._session.execute(
            select(CommandRecord).order_by(CommandRecord.id.desc()).limit(limit)
        )
        return list(result.scalars())

    async def purge_older_than(self, ts: int) -> int:
        """Ретенция журнала (30 дней): удаляет завершённые команды старше ts."""
        result = await self._session.execute(
            delete(CommandRecord).where(
                CommandRecord.created_at < ts,
                CommandRecord.status.not_in(_ACTIVE_STATUSES),
            )
        )
        return rowcount(result)

    async def supersede(self, command_ids: Sequence[int], *, finished_at: int) -> None:
        if not command_ids:
            return
        await self._session.execute(
            update(CommandRecord)
            .where(CommandRecord.id.in_(command_ids))
            .values(status=CommandStatus.SUPERSEDED, finished_at=finished_at)
        )
