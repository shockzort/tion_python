"""Бэкапы БД: ежедневный ``VACUUM INTO`` + gzip, ретенция 7 (NFR-7).

Снапшот атомарен на уровне SQLite (VACUUM INTO пишет согласованную копию,
не блокируя WAL-писателей), затем сжимается в потоке. Провал публикует
``backup.failed`` — подписчики (web push) уведомят владельца. Восстановление —
процедура в runbook: остановить сервис, распаковать снапшот на место БД.
"""

from __future__ import annotations

import asyncio
import contextlib
import gzip
import shutil
from datetime import datetime, timedelta, tzinfo
from pathlib import Path

import structlog

from easy_breezy.automation.clock import Clock
from easy_breezy.core.events import (
    TOPIC_BACKUP_FAILED,
    TOPIC_BACKUP_FINISHED,
    EventBus,
)
from easy_breezy.storage.database import Database

log = structlog.get_logger(__name__)

RETENTION_COUNT = 7
BACKUP_HOUR = 3
BACKUP_MINUTE = 30
_PREFIX = "easy_breezy-"
_SUFFIX = ".db.gz"


class BackupError(Exception):
    """Снапшот не создан (диск, блокировка, повреждение)."""


class BackupService:
    def __init__(
        self,
        db: Database,
        events: EventBus,
        data_dir: Path,
        clock: Clock,
        *,
        tz: tzinfo,
        retention: int = RETENTION_COUNT,
    ) -> None:
        self._db = db
        self._events = events
        self._dir = data_dir / "backups"
        self._clock = clock
        self._tz = tz
        self._retention = retention
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="backup-daily")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            delay = self.next_run(self._clock.now()) - self._clock.now()
            await self._clock.sleep(delay)
            try:
                await self.run_backup()
            except asyncio.CancelledError:
                raise
            except Exception:
                # бэкап не имеет права умирать молча (ADR-0007);
                # публикация backup.failed — в run_backup
                log.exception("backup_loop_crashed")

    def next_run(self, now: float) -> float:
        """Ближайшие 03:30 локальной таймзоны (ночью шина спокойна)."""
        local = datetime.fromtimestamp(now, self._tz)
        target = local.replace(
            hour=BACKUP_HOUR, minute=BACKUP_MINUTE, second=0, microsecond=0
        )
        if target <= local:
            target += timedelta(days=1)
        return target.timestamp()

    async def run_backup(self) -> Path:
        """Создаёт снапшот; возвращает путь архива. Ошибка → backup.failed."""
        stamp = datetime.fromtimestamp(self._clock.now(), self._tz).strftime(
            "%Y%m%d-%H%M%S"
        )
        archive = self._dir / f"{_PREFIX}{stamp}{_SUFFIX}"
        raw = self._dir / f"{_PREFIX}{stamp}.db.tmp"
        try:
            await asyncio.to_thread(_prepare_dir, self._dir, raw)
            await self._vacuum_into(raw)
            size = await asyncio.to_thread(_gzip_file, raw, archive)
            purged = await asyncio.to_thread(
                _apply_retention, self._dir, self._retention
            )
        except Exception as exc:
            log.exception("backup_failed", archive=str(archive))
            self._events.publish(TOPIC_BACKUP_FAILED, {"error": str(exc)})
            raise BackupError(str(exc)) from exc
        finally:
            await asyncio.to_thread(_unlink_quiet, raw)
        log.info("backup_done", archive=archive.name, size=size, purged=purged)
        self._events.publish(
            TOPIC_BACKUP_FINISHED, {"archive": archive.name, "size": size}
        )
        return archive

    async def _vacuum_into(self, target: Path) -> None:
        escaped = str(target).replace("'", "''")
        async with self._db.engine.connect() as connection:
            autocommit = await connection.execution_options(
                isolation_level="AUTOCOMMIT"
            )
            await autocommit.exec_driver_sql(f"VACUUM INTO '{escaped}'")


def _prepare_dir(directory: Path, raw: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    raw.unlink(missing_ok=True)


def _unlink_quiet(path: Path) -> None:
    # уборка не смеет затмить причину провала (NotADirectory и подобное)
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _apply_retention(directory: Path, retention: int) -> int:
    """Держит последние N архивов; возвращает число удалённых."""
    archives = sorted(directory.glob(f"{_PREFIX}*{_SUFFIX}"))
    stale = archives[:-retention] if retention > 0 else archives
    for path in stale:
        path.unlink(missing_ok=True)
    return len(stale)


def _gzip_file(source: Path, target: Path) -> int:
    with source.open("rb") as raw, gzip.open(target, "wb", compresslevel=6) as packed:
        shutil.copyfileobj(raw, packed)
    return target.stat().st_size


def restore_archive(archive: Path, database_path: Path) -> None:
    """Распаковывает снапшот на место БД (сервис должен быть остановлен).

    Используется runbook-процедурой и тестом восстановления; WAL/SHM-хвосты
    прежней БД удаляются — они принадлежат старому файлу.
    """
    with gzip.open(archive, "rb") as packed, database_path.open("wb") as out:
        shutil.copyfileobj(packed, out)
    for tail in ("-wal", "-shm"):
        Path(str(database_path) + tail).unlink(missing_ok=True)
