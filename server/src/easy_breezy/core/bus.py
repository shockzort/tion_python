"""Командная шина: идемпотентность, per-device сериализация, приоритеты, журнал.

План §8. Итог команды — фактическое состояние после контрольного перечитывания
(ADR-0004): расхождение запрошенного с применённым не ретраится (прошивка
вправе корректировать поля, внешние контроллеры — перезаписывать), а
логируется; вызывающий получает истину устройства в ``result_state``.

Один воркер на устройство сериализует записи: SET_PARAMS шлёт полный набор,
поэтому дельта мержится поверх последнего подтверждённого состояния
непосредственно перед записью — параллельные записи теряли бы поля.
"""

from __future__ import annotations

import asyncio
import bisect
import contextlib
import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.exc import IntegrityError

from easy_breezy.ble.driver import DriverError, DriverTimeoutError, S4Driver
from easy_breezy.ble.protocol.s4 import S4State
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.events import TOPIC_COMMAND_FINISHED, EventBus
from easy_breezy.core.holds import HoldManager
from easy_breezy.core.model import StateDelta, state_to_dict
from easy_breezy.core.registry import DeviceRegistry
from easy_breezy.storage import Database
from easy_breezy.storage.models import CommandSource, CommandStatus
from easy_breezy.storage.repos import CommandRepo

log = structlog.get_logger(__name__)

JOURNAL_RETENTION_SECONDS = 30 * 86400

_MANUAL_PRIORITY = 0
_DEFAULT_PRIORITY: dict[CommandSource, int] = {
    CommandSource.UI: 0,
    CommandSource.YANDEX: 0,
    CommandSource.CLI: 0,
    CommandSource.INTENT: 0,
    CommandSource.TRIGGER: 1,
    CommandSource.SCENARIO: 2,
    CommandSource.SCHEDULE: 2,
}

_UNREACHABLE = "устройство недоступно"


class CommandError(Exception):
    """Некорректная заявка в командную шину."""


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """Итог команды — то, что уходит в REST-ответ и журнал."""

    command_id: int
    status: CommandStatus
    result_state: dict[str, Any] | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CommandTicket:
    """Квитанция submit: id для 202-ответа и общий Future итога (дедуп)."""

    command_id: int
    outcome: asyncio.Future[CommandOutcome]


@dataclass(order=True)
class _QueueItem:
    priority: int
    seq: int
    command_id: int = field(compare=False)
    device_uuid: str = field(compare=False)
    key: str = field(compare=False)
    delta: StateDelta = field(compare=False)


class _DeviceQueue:
    """Очередь одного устройства: (priority, seq)-порядок, один потребитель."""

    def __init__(self) -> None:
        self._items: list[_QueueItem] = []
        self._nonempty = asyncio.Event()

    def push(self, item: _QueueItem) -> None:
        bisect.insort(self._items, item)
        self._nonempty.set()

    async def pop(self) -> _QueueItem:
        while not self._items:
            self._nonempty.clear()
            await self._nonempty.wait()
        item = self._items.pop(0)
        if not self._items:
            self._nonempty.clear()
        return item

    def evict_stale(self, max_depth: int) -> list[_QueueItem]:
        """Anti-flood: пока глубина > max_depth, снимает старейшие priority=2."""
        evicted: list[_QueueItem] = []
        while len(self._items) > max_depth:
            stale = [item for item in self._items if item.priority == 2]
            if not stale:
                break
            oldest = min(stale, key=lambda item: item.seq)
            self._items.remove(oldest)
            evicted.append(oldest)
        return evicted


class CommandBus:
    def __init__(
        self,
        db: Database,
        registry: DeviceRegistry,
        events: EventBus,
        holds: HoldManager,
        *,
        now: Callable[[], float] = time.time,
        execute_budget: float = 4.0,
        max_queue_depth: int = 8,
    ) -> None:
        self._db = db
        self._registry = registry
        self._events = events
        self._holds = holds
        self._now = now
        self._budget = execute_budget
        self._max_depth = max_queue_depth
        self._seq = itertools.count()
        self._queues: dict[str, _DeviceQueue] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._tickets: dict[str, CommandTicket] = {}

    async def start(self) -> None:
        """Восстановление журнала: зависшие с прошлого запуска — failed;
        завершённые старше 30 дней — удаляются."""
        now = int(self._now())
        async with self._db.session() as session:
            repo = CommandRepo(session)
            interrupted = await repo.fail_interrupted(finished_at=now)
            purged = await repo.purge_older_than(now - JOURNAL_RETENTION_SECONDS)
        if interrupted or purged:
            log.info(
                "command_journal_recovered", interrupted=interrupted, purged=purged
            )

    async def stop(self) -> None:
        workers = list(self._workers.values())
        self._workers.clear()
        for task in workers:
            task.cancel()
        for task in workers:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for ticket in self._tickets.values():
            if not ticket.outcome.done():
                ticket.outcome.cancel()
        self._tickets.clear()
        self._queues.clear()

    async def submit(
        self,
        *,
        device_uuid: str,
        delta: StateDelta,
        source: CommandSource,
        idempotency_key: str,
        priority: int | None = None,
    ) -> CommandTicket:
        """Ставит команду в очередь устройства; дедуп по ключу идемпотентности.

        Повторный submit того же ключа возвращает ту же квитанцию (команда в
        полёте — общий Future; завершена — Future с сохранённым итогом).
        """
        if delta.is_empty():
            raise CommandError("пустая дельта — нечего применять")
        if self._registry.supervisor(device_uuid) is None:
            raise CommandError(f"устройство {device_uuid} не в реестре")

        existing = self._tickets.get(idempotency_key)
        if existing is not None:
            log.debug("command_dedup_inflight", key=idempotency_key)
            return existing
        stored = await self._ticket_from_journal(idempotency_key)
        if stored is not None:
            return stored

        resolved_priority = (
            priority if priority is not None else _DEFAULT_PRIORITY[source]
        )
        try:
            async with self._db.session() as session:
                record = await CommandRepo(session).insert(
                    idempotency_key=idempotency_key,
                    device_uuid=device_uuid,
                    source=source.value,
                    priority=resolved_priority,
                    payload=delta.to_payload(),
                    created_at=int(self._now()),
                )
                command_id = record.id
        except IntegrityError:
            # гонка одинаковых ключей — победитель уже в журнале или в полёте
            existing = self._tickets.get(idempotency_key)
            if existing is not None:
                return existing
            stored = await self._ticket_from_journal(idempotency_key)
            if stored is None:
                raise CommandError("журнал не принял команду") from None
            return stored

        loop = asyncio.get_running_loop()
        ticket = CommandTicket(command_id, loop.create_future())
        self._tickets[idempotency_key] = ticket
        item = _QueueItem(
            resolved_priority,
            next(self._seq),
            command_id,
            device_uuid,
            idempotency_key,
            delta,
        )
        queue = self._queues.setdefault(device_uuid, _DeviceQueue())
        queue.push(item)
        await self._evict_stale(queue)
        if device_uuid not in self._workers:
            self._workers[device_uuid] = asyncio.create_task(
                self._worker(device_uuid), name=f"command-worker-{device_uuid}"
            )
        return ticket

    async def _ticket_from_journal(self, key: str) -> CommandTicket | None:
        """Квитанция по сохранённой записи журнала (обычно терминальной).

        Нетерминальная запись без квитанции в памяти невозможна в одном
        процессе (восстановление старта помечает зависшие failed) — если
        встретилась, отдаём снимок как есть.
        """
        async with self._db.session() as session:
            record = await CommandRepo(session).get_by_key(key)
        if record is None:
            return None
        outcome = CommandOutcome(
            record.id,
            CommandStatus(record.status),
            result_state=record.result_state,
            error=record.error,
        )
        future: asyncio.Future[CommandOutcome] = (
            asyncio.get_running_loop().create_future()
        )
        future.set_result(outcome)
        log.debug("command_dedup_journal", key=key, status=record.status)
        return CommandTicket(record.id, future)

    async def _evict_stale(self, queue: _DeviceQueue) -> None:
        evicted = queue.evict_stale(self._max_depth)
        if not evicted:
            return
        async with self._db.session() as session:
            await CommandRepo(session).supersede(
                [item.command_id for item in evicted], finished_at=int(self._now())
            )
        for item in evicted:
            log.info("command_superseded", command_id=item.command_id)
            self._finalize(
                item, CommandOutcome(item.command_id, CommandStatus.SUPERSEDED)
            )

    async def _worker(self, device_uuid: str) -> None:
        queue = self._queues[device_uuid]
        while True:
            item = await queue.pop()
            try:
                outcome = await self._execute(item)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("command_worker_error", command_id=item.command_id)
                outcome = CommandOutcome(
                    item.command_id,
                    CommandStatus.FAILED,
                    error="внутренняя ошибка исполнения",
                )
            async with self._db.session() as session:
                await CommandRepo(session).finish(
                    outcome.command_id,
                    status=outcome.status,
                    finished_at=int(self._now()),
                    result_state=outcome.result_state,
                    error=outcome.error,
                )
            self._finalize(item, outcome)

    async def _execute(self, item: _QueueItem) -> CommandOutcome:
        if item.priority > _MANUAL_PRIORITY and self._holds.is_held(item.device_uuid):
            log.info(
                "command_skipped_hold",
                command_id=item.command_id,
                device_uuid=item.device_uuid,
            )
            return CommandOutcome(item.command_id, CommandStatus.SKIPPED_HOLD)

        async with self._db.session() as session:
            await CommandRepo(session).mark_running(
                item.command_id, started_at=int(self._now())
            )

        timed_out = False
        last_error = _UNREACHABLE
        for attempt in (1, 2):  # бюджет исполнения + один ретрай (план §8)
            driver = self._online_driver(item.device_uuid)
            if driver is None:
                timed_out = False
                last_error = _UNREACHABLE
                break
            try:
                actual = await self._apply(driver, item.delta)
            except TimeoutError:
                timed_out = True
                last_error = f"нет итога за бюджет {self._budget} с"
            except DriverError as exc:
                timed_out = isinstance(exc, DriverTimeoutError)
                last_error = str(exc)
            else:
                if item.priority == _MANUAL_PRIORITY:
                    until = self._holds.place(item.device_uuid)
                    log.debug(
                        "manual_hold_placed",
                        device_uuid=item.device_uuid,
                        until=int(until),
                    )
                self._log_adjustments(item, actual)
                return CommandOutcome(
                    item.command_id,
                    CommandStatus.DONE,
                    result_state=state_to_dict(actual),
                )
            log.warning(
                "command_attempt_failed",
                command_id=item.command_id,
                attempt=attempt,
                error=last_error,
            )
        status = CommandStatus.TIMEOUT if timed_out else CommandStatus.FAILED
        return CommandOutcome(item.command_id, status, error=last_error)

    async def _apply(self, driver: S4Driver, delta: StateDelta) -> S4State:
        """Мерж дельты поверх фактического состояния и запись полного набора."""
        async with asyncio.timeout(self._budget):
            base = driver.last_state
            if base is None:
                base = await driver.get_state()
            return await driver.set_state(delta.apply_to(base))

    def _online_driver(self, device_uuid: str) -> S4Driver | None:
        supervisor = self._registry.supervisor(device_uuid)
        if (
            supervisor is None
            or supervisor.connection_state is not ConnectionState.ONLINE
        ):
            return None
        return supervisor.driver

    def _log_adjustments(self, item: _QueueItem, actual: S4State) -> None:
        """Сверка ADR-0004: что из запрошенного прошивка скорректировала."""
        actual_dict = state_to_dict(actual)
        adjusted = {
            name: {"wanted": wanted, "actual": actual_dict[name]}
            for name, wanted in item.delta.to_payload().items()
            if actual_dict[name] != wanted
        }
        if adjusted:
            log.warning(
                "set_adjusted_by_device",
                command_id=item.command_id,
                device_uuid=item.device_uuid,
                adjusted=adjusted,
            )

    def _finalize(self, item: _QueueItem, outcome: CommandOutcome) -> None:
        ticket = self._tickets.pop(item.key, None)
        if ticket is not None and not ticket.outcome.done():
            ticket.outcome.set_result(outcome)
        data: dict[str, Any] = {
            "command_id": outcome.command_id,
            "device_uuid": item.device_uuid,
            "status": outcome.status.value,
        }
        if outcome.result_state is not None:
            data["result_state"] = outcome.result_state
        if outcome.error is not None:
            data["error"] = outcome.error
        self._events.publish(TOPIC_COMMAND_FINISHED, data)
