"""Движок триггеров: защёлка с гистерезисом, кулдаун, окно (план §9, FR-22).

Оценка событийная — на каждое ``sensor.updated``; решение по одному
измерению — чистая функция ``decide`` (табличные тесты). Защёлка:
enter при пересечении порога (вне кулдауна и в окне) → enter-действия;
exit при возврате за порог ∓ гистерезис → exit-действия. Молчащий датчик
(>10 мин) отмечается warning-логом минутного sweep, защёлка держится —
исчезновение данных не повод дёргать устройства.

Maintain-триггеры (поддержание CO₂) оцениваются на тех же измерениях:
чистая функция ``decide_speed`` (``automation/maintain.py``) считает
ступенчатую корректировку скорости в диапазоне [speed_min..speed_max]
по последнему подтверждённому состоянию из StateCache. Кулдаун — от
фактической постановки команды; устройства под manual-hold и офлайн
пропускаются ДО постановки (без спама skipped_hold в журнал и без
сжигания кулдауна — регулирование возобновляется сразу после hold).

Действия исполняются через ScenarioService с приоритетом триггера (1):
manual-hold пропускает их со статусом ``skipped_hold`` (FR-23), внутри
автоматики триггер обгоняет расписание (план §9).
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime, tzinfo
from typing import Any, Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.automation.clock import Clock
from easy_breezy.automation.maintain import (
    DEFAULT_DEADBAND,
    KIND_MAINTAIN,
    decide_speed,
    expand_targets,
)
from easy_breezy.automation.scenarios import ScenarioError, ScenarioService
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.events import TOPIC_SENSOR_UPDATED, EventBus, Subscription
from easy_breezy.core.holds import HoldManager
from easy_breezy.core.state import StateCache
from easy_breezy.storage import Database
from easy_breezy.storage.models import CommandSource, Trigger
from easy_breezy.storage.repos import SensorRepo, TriggerRepo

log = structlog.get_logger(__name__)

SILENT_AFTER_SECONDS = 600.0
"""Датчик без данных дольше 10 минут — warning в sweep."""

_SWEEP_INTERVAL = 60.0

OPS = (">", "<")


@dataclass(frozen=True, slots=True)
class TriggerDecision:
    """Смена состояния защёлки по одному измерению."""

    fired: Literal["enter", "exit"]
    active: bool


def in_window(
    window_start: str | None, window_end: str | None, ts: float, tz: tzinfo
) -> bool:
    """Попадает ли момент в окно HH:MM (окно через полночь допустимо)."""
    if window_start is None or window_end is None:
        return True
    local = datetime.fromtimestamp(ts, tz=tz)
    current = local.strftime("%H:%M")
    if window_start <= window_end:
        return window_start <= current < window_end
    return current >= window_start or current < window_end


def decide(
    trigger: Trigger, value: float, ts: float, *, tz: tzinfo
) -> TriggerDecision | None:
    """Решение защёлки по измерению; None — состояние не меняется."""
    if trigger.op == ">":
        crossed_enter = value > trigger.threshold
        crossed_exit = value < trigger.threshold - trigger.hysteresis
    else:
        crossed_enter = value < trigger.threshold
        crossed_exit = value > trigger.threshold + trigger.hysteresis

    if trigger.is_active:
        # выход оценивается всегда — возврат к норме не ограничен окном
        if crossed_exit:
            return TriggerDecision("exit", False)
        return None

    if not crossed_enter:
        return None
    if (
        trigger.last_fired_at is not None
        and ts - trigger.last_fired_at < trigger.cooldown_s
    ):
        return None
    if not in_window(trigger.window_start, trigger.window_end, ts, tz):
        return None
    return TriggerDecision("enter", True)


@dataclass(frozen=True, slots=True)
class _FirePlan:
    trigger_id: int
    name: str
    fired: Literal["enter", "exit", "maintain"]
    value: float
    ts: int
    scenario_id: int | None
    actions: list[Any] | None


class TriggerEngine:
    def __init__(
        self,
        db: Database,
        scenarios: ScenarioService,
        events: EventBus,
        clock: Clock,
        *,
        cache: StateCache,
        holds: HoldManager,
        tz: tzinfo,
    ) -> None:
        self._db = db
        self._scenarios = scenarios
        self._events = events
        self._clock = clock
        self._cache = cache
        self._holds = holds
        self._tz = tz
        self._tasks: list[asyncio.Task[None]] = []
        self._subscription: Subscription | None = None
        self._silent_ids: set[int] = set()
        """Датчики, о молчании которых уже предупредили (без спама)."""

    async def start(self) -> None:
        self._subscription = self._events.subscribe(TOPIC_SENSOR_UPDATED)
        self._tasks = [
            asyncio.create_task(
                self._watch_loop(self._subscription), name="trigger-engine"
            ),
            asyncio.create_task(self._sweep_loop(), name="trigger-sweep"),
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

    async def _watch_loop(self, subscription: Subscription) -> None:
        async for event in subscription:
            try:
                await self.evaluate(
                    int(event.data["sensor_id"]),
                    dict(event.data["metrics"]),
                    float(event.data["ts"]),
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # движок триггеров не имеет права умирать молча (ADR-0007)
                log.exception("trigger_evaluation_crashed")

    async def evaluate(
        self, sensor_id: int, metrics: dict[str, float], ts: float
    ) -> int:
        """Оценивает триггеры датчика по измерению; возвращает число запусков."""
        self._silent_ids.discard(sensor_id)
        plans: list[_FirePlan] = []
        async with self._db.session() as session:
            triggers = await TriggerRepo(session).list_enabled_for_sensor(sensor_id)
            for trigger in triggers:
                value = metrics.get(trigger.metric)
                if value is None:
                    continue
                if trigger.kind == KIND_MAINTAIN:
                    plan = await self._plan_maintain(trigger, value, ts, session)
                    if plan is not None:
                        plans.append(plan)
                    continue
                decision = decide(trigger, value, ts, tz=self._tz)
                if decision is None:
                    continue
                trigger.is_active = decision.active
                if decision.fired == "enter":
                    trigger.last_fired_at = int(ts)
                plans.append(
                    _FirePlan(
                        trigger.id,
                        trigger.name,
                        decision.fired,
                        value,
                        int(ts),
                        (
                            trigger.enter_scenario_id
                            if decision.fired == "enter"
                            else trigger.exit_scenario_id
                        ),
                        (
                            trigger.enter_actions
                            if decision.fired == "enter"
                            else trigger.exit_actions
                        ),
                    )
                )
        for plan in plans:
            await self._execute(plan)
        return len(plans)

    async def _plan_maintain(
        self, trigger: Trigger, value: float, ts: float, session: AsyncSession
    ) -> _FirePlan | None:
        """Корректировки поддержания CO₂ по одному измерению.

        Кулдаун сгорает только при фактической постановке команды:
        устройства под hold/офлайн пропускаются заранее, чтобы после
        снятия hold регулирование продолжилось без ожидания.
        """
        if not in_window(trigger.window_start, trigger.window_end, ts, self._tz):
            return None
        if (
            trigger.last_fired_at is not None
            and ts - trigger.last_fired_at < trigger.cooldown_s
        ):
            return None
        if trigger.speed_min is None or trigger.speed_max is None:
            log.warning("maintain_misconfigured", trigger_id=trigger.id)
            return None
        deadband = trigger.hysteresis if trigger.hysteresis > 0 else DEFAULT_DEADBAND
        actions: list[Any] = []
        for device_uuid in sorted(await expand_targets(session, trigger.targets)):
            snapshot = self._cache.get(device_uuid)
            if (
                snapshot is None
                or snapshot.state is None
                or snapshot.connection is not ConnectionState.ONLINE
            ):
                log.debug(
                    "maintain_skipped_offline",
                    trigger_id=trigger.id,
                    device_uuid=device_uuid,
                )
                continue
            if self._holds.is_held(device_uuid):
                log.info(
                    "maintain_skipped_hold",
                    trigger_id=trigger.id,
                    device_uuid=device_uuid,
                )
                continue
            delta = decide_speed(
                value=value,
                target=trigger.threshold,
                deadband=deadband,
                current_speed=snapshot.state.fan_speed,
                power_on=snapshot.state.power,
                speed_min=trigger.speed_min,
                speed_max=trigger.speed_max,
            )
            if delta is None:
                continue
            actions.append(
                {
                    "target_type": "device",
                    "target_id": device_uuid,
                    "delta": delta.to_payload(),
                }
            )
        if not actions:
            return None
        trigger.last_fired_at = int(ts)
        return _FirePlan(
            trigger.id, trigger.name, "maintain", value, int(ts), None, actions
        )

    async def _execute(self, plan: _FirePlan) -> None:
        log.info(
            "trigger_fired",
            trigger_id=plan.trigger_id,
            name=plan.name,
            edge=plan.fired,
            value=plan.value,
        )
        prefix = f"trigger:{plan.trigger_id}:{plan.fired}:{plan.ts}"
        try:
            if plan.scenario_id is not None:
                await self._scenarios.run(
                    plan.scenario_id,
                    source=CommandSource.TRIGGER,
                    idempotency_prefix=prefix,
                )
            elif plan.actions:
                await self._scenarios.run_actions(
                    plan.actions,
                    source=CommandSource.TRIGGER,
                    idempotency_prefix=prefix,
                )
            # ни сценария, ни действий — защёлка просто меняет состояние
        except ScenarioError as exc:
            log.warning(
                "trigger_fire_failed", trigger_id=plan.trigger_id, error=str(exc)
            )

    async def _sweep_loop(self) -> None:
        while True:
            try:
                await self._clock.sleep(_SWEEP_INTERVAL)
                await self.run_sweep()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("trigger_sweep_crashed")

    async def run_sweep(self) -> None:
        """Отмечает молчащие датчики (warning один раз, защёлки не трогаются)."""
        now = self._clock.now()
        async with self._db.session() as session:
            sensors = await SensorRepo(session).list_all()
        for sensor in sensors:
            silent = (
                sensor.last_seen_at is None
                or now - sensor.last_seen_at > SILENT_AFTER_SECONDS
            )
            if silent and sensor.id not in self._silent_ids:
                self._silent_ids.add(sensor.id)
                log.warning(
                    "sensor_silent",
                    sensor_id=sensor.id,
                    name=sensor.name,
                    last_seen_at=sensor.last_seen_at,
                )
            elif not silent:
                self._silent_ids.discard(sensor.id)
