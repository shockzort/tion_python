"""Репозиторий пользовательских предпочтений (key/value JSON per-user)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import UserPref


class UserPrefRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int, key: str) -> UserPref | None:
        return await self._session.get(UserPref, (user_id, key))

    async def set(self, user_id: int, key: str, value: Any, *, updated_at: int) -> None:
        await self._session.merge(
            UserPref(user_id=user_id, key=key, value=value, updated_at=updated_at)
        )
