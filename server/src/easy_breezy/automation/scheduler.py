"""Планировщик расписаний: один вечный task поверх croniter (план §9, FR-21).

У каждого расписания есть курсор — докуда обработана ось времени. Шаг
планировщика собирает cron-срабатывания в интервале (курсор, сейчас]:
последнее исполняется, если опоздание не больше допуска (5 минут — рестарт
или короткий простой), более старые пропускаются с логом. Ключ
идемпотентности ``schedule:{id}:{fire_ts}`` делает исполнение exactly-once
даже при падении между запуском и сдвигом курсора.

Время — только через ``Clock`` (time-travel тесты); таймзона расписаний
инжектируется. Пробуждение — по ближайшему срабатыванию или событию
``automation.changed`` (CRUD из REST).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

import structlog
from croniter import croniter

from easy_breezy.automation.clock import Clock
from easy_breezy.automation.scenarios import ScenarioError, ScenarioService
from easy_breezy.core.events import TOPIC_AUTOMATION_CHANGED, EventBus, Subscription
from easy_breezy.storage import Database
from easy_breezy.storage.models import CommandSource, Schedule
from easy_breezy.storage.repos import ScheduleRepo

log = structlog.get_logger(__name__)

LATE_TOLERANCE_SECONDS = 300.0
"""Максимальное опоздание, при котором пропущенное срабатывание исполняется."""

_MAX_IDLE_SLEEP = 3600.0
_CATCHUP_LIMIT = 1000
"""Предохранитель перебора пропущенных срабатываний после долгого простоя."""


def resolve_timezone(name: str | None) -> tzinfo:
    """Таймзона расписаний: IANA-имя из настроек или системная локальная.

    Без явного имени берётся текущее локальное смещение — для зон с сезонными
    переходами задавайте ``EB_TIMEZONE`` явно, иначе смещение обновится только
    с рестартом сервиса.
    """
    if name is not None:
        return ZoneInfo(name)
    local = datetime.now().astimezone().tzinfo
    return local if local is not None else UTC


def validate_cron(expression: str) -> bool:
    """Пять полей и разбираемость croniter (формат FR-21)."""
    return len(expression.split()) == 5 and croniter.is_valid(expression)


@dataclass(frozen=True, slots=True)
class _Plan:
    """Решение по одному расписанию на текущем шаге."""

    schedule_id: int
    name: str
    scenario_id: int | None
    actions: list[Any] | None
    new_cursor: int
    fire_ts: int | None
    """Срабатывание к исполнению; None — только сдвиг курсора."""
    skipped: int


class SchedulerService:
    def __init__(
        self,
        db: Database,
        scenarios: ScenarioService,
        events: EventBus,
        clock: Clock,
        *,
        tz: tzinfo,
        late_tolerance: float = LATE_TOLERANCE_SECONDS,
    ) -> None:
        self._db = db
        self._scenarios = scenarios
        self._events = events
        self._clock = clock
        self._tz = tz
        self._tolerance = late_tolerance
        self._wakeup = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._subscription: Subscription | None = None

    async def start(self) -> None:
        # подписка синхронно — CRUD между start() и запуском задач не теряется
        self._subscription = self._events.subscribe(TOPIC_AUTOMATION_CHANGED)
        self._tasks = [
            asyncio.create_task(self._loop(), name="scheduler"),
            asyncio.create_task(
                self._watch_changes(self._subscription), name="scheduler-wakeup"
            ),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []
        if self._subscription is not None:
            self._subscription.close()
            self._subscription = None

    async def _watch_changes(self, subscription: Subscription) -> None:
        async for _ in subscription:
            self._wakeup.set()

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_pending()
                delay = await self._idle_delay()
            except asyncio.CancelledError:
                raise
            except Exception:
                # планировщик не имеет права умирать молча (ADR-0007)
                log.exception("scheduler_iteration_crashed")
                delay = 5.0
            await self._wait(delay)

    async def run_pending(self) -> int:
        """Обрабатывает наступившие срабатывания; возвращает число исполненных.

        Курсор пишется после исполнения: падение между ними даёт повтор
        запуска, который дедупится журналом команд по ключу идемпотентности.
        """
        now = self._clock.now()
        async with self._db.session() as session:
            schedules = await ScheduleRepo(session).list_enabled()
            plans = [self._plan(schedule, now) for schedule in schedules]
        fired = 0
        for plan in plans:
            if plan is None:
                continue
            if plan.skipped:
                log.warning(
                    "schedule_missed",
                    schedule_id=plan.schedule_id,
                    name=plan.name,
                    skipped=plan.skipped,
                )
            if plan.fire_ts is not None:
                await self._fire(plan, plan.fire_ts)
                fired += 1
            async with self._db.session() as session:
                schedule = await ScheduleRepo(session).get(plan.schedule_id)
                if schedule is not None:
                    schedule.cursor_ts = plan.new_cursor
        return fired

    def _plan(self, schedule: Schedule, now: float) -> _Plan | None:
        """Чистое решение по расписанию: что исполнить и куда сдвинуть курсор."""
        if schedule.cursor_ts is None:
            # первое знакомство: курсор — «сейчас», прошлое не догоняется
            return _Plan(
                schedule.id,
                schedule.name,
                schedule.scenario_id,
                schedule.actions,
                new_cursor=int(now),
                fire_ts=None,
                skipped=0,
            )
        due = self._due_occurrences(schedule.cron, schedule.cursor_ts, now)
        if not due:
            return None
        last = due[-1]
        on_time = now - last <= self._tolerance
        return _Plan(
            schedule.id,
            schedule.name,
            schedule.scenario_id,
            schedule.actions,
            new_cursor=int(last),
            fire_ts=int(last) if on_time else None,
            skipped=len(due) - 1 if on_time else len(due),
        )

    def _due_occurrences(self, cron: str, cursor: float, now: float) -> list[float]:
        """Cron-срабатывания в интервале (cursor, now] в таймзоне расписаний."""
        base = datetime.fromtimestamp(cursor, tz=self._tz)
        it = croniter(cron, base)
        due: list[float] = []
        while len(due) < _CATCHUP_LIMIT:
            candidate = it.get_next(datetime).timestamp()
            if candidate > now:
                break
            due.append(candidate)
        return due

    def _next_fire(self, cron: str, after: float) -> float:
        base = datetime.fromtimestamp(after, tz=self._tz)
        return croniter(cron, base).get_next(datetime).timestamp()

    async def _fire(self, plan: _Plan, fire_ts: int) -> None:
        prefix = f"schedule:{plan.schedule_id}:{fire_ts}"
        log.info(
            "schedule_fired",
            schedule_id=plan.schedule_id,
            name=plan.name,
            fire_ts=fire_ts,
        )
        try:
            if plan.scenario_id is not None:
                await self._scenarios.run(
                    plan.scenario_id,
                    source=CommandSource.SCHEDULE,
                    idempotency_prefix=prefix,
                )
            else:
                await self._scenarios.run_actions(
                    plan.actions or [],
                    source=CommandSource.SCHEDULE,
                    idempotency_prefix=prefix,
                )
        except ScenarioError as exc:
            log.warning(
                "schedule_fire_failed", schedule_id=plan.schedule_id, error=str(exc)
            )

    async def _idle_delay(self) -> float:
        """Пауза до ближайшего срабатывания (или дежурный час без расписаний)."""
        now = self._clock.now()
        delay = _MAX_IDLE_SLEEP
        async with self._db.session() as session:
            for schedule in await ScheduleRepo(session).list_enabled():
                base = schedule.cursor_ts if schedule.cursor_ts is not None else now
                upcoming = self._next_fire(schedule.cron, base)
                delay = min(delay, max(upcoming - now, 0.0))
        return delay

    async def _wait(self, delay: float) -> None:
        """Сон до ближайшего дела с прерыванием по ``automation.changed``."""
        if self._wakeup.is_set():
            self._wakeup.clear()
            return
        sleeper = asyncio.ensure_future(self._clock.sleep(delay))
        waker = asyncio.ensure_future(self._wakeup.wait())
        try:
            await asyncio.wait((sleeper, waker), return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (sleeper, waker):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._wakeup.clear()
