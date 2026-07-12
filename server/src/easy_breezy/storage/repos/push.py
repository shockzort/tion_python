"""Репозиторий web push подписок."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import PushSubscription
from easy_breezy.storage.repos._util import rowcount


class PushRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self, *, endpoint: str, keys: dict[str, Any], created_at: int
    ) -> PushSubscription:
        existing = await self.get_by_endpoint(endpoint)
        if existing is not None:
            existing.keys = keys
            return existing
        subscription = PushSubscription(
            endpoint=endpoint, keys=keys, created_at=created_at
        )
        self._session.add(subscription)
        await self._session.flush()
        return subscription

    async def get_by_endpoint(self, endpoint: str) -> PushSubscription | None:
        result = await self._session.execute(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[PushSubscription]:
        result = await self._session.execute(
            select(PushSubscription).order_by(PushSubscription.id)
        )
        return list(result.scalars())

    async def delete_by_endpoint(self, endpoint: str) -> bool:
        result = await self._session.execute(
            delete(PushSubscription).where(PushSubscription.endpoint == endpoint)
        )
        return rowcount(result) > 0
