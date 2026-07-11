"""Репозиторий настроек key/value (JSON)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import Setting


class SettingsRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str, default: Any = None) -> Any:
        setting = await self._session.get(Setting, key)
        return default if setting is None else setting.value

    async def set(self, key: str, value: Any) -> None:
        await self._session.merge(Setting(key=key, value=value))
