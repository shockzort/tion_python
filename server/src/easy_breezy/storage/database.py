"""Движок SQLite: async-engine, сессии-транзакции, программные миграции.

PRAGMA-профиль плана §5: WAL, busy_timeout=5000, foreign_keys=ON.
Миграции лежат внутри пакета (``storage/migrations``) — сервис применяет их
сам при старте из любого cwd; тот же путь использует CLI Alembic
(``server/alembic.ini``).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    """Доступ к БД одного процесса: фабрика сессий и миграции."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(url)
        _install_sqlite_pragmas(self.engine)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Сессия в транзакции: commit на выходе, rollback при исключении."""
        async with self.sessions() as session, session.begin():
            yield session

    async def migrate(self) -> None:
        """Применяет миграции до head (Alembic синхронный — в поток)."""
        await asyncio.to_thread(_upgrade_to_head, self.url)

    async def dispose(self) -> None:
        await self.engine.dispose()


def alembic_config(url: str) -> AlembicConfig:
    """Конфигурация Alembic без ini-файла — пригодна из любого cwd."""
    config = AlembicConfig()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    config.set_main_option("sqlalchemy.url", url)
    return config


def _upgrade_to_head(url: str) -> None:
    alembic_command.upgrade(alembic_config(url), "head")


def _install_sqlite_pragmas(engine: AsyncEngine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_connection: Any, _record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
