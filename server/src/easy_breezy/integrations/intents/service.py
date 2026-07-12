"""Исполнение интентов: каталог → разбор → шина → человекочитаемый ответ.

Интент — ручное управление (FR-23): команды идут с приоритетом 0 и ставят
manual-hold, как нажатие в UI или фраза Алисе. Итог ждём ограниченно
(``command_wait_seconds``): всё исполнилось — «Готово», часть в полёте —
честное «Выполняю», отказ — причина.
"""

from __future__ import annotations

import asyncio
import time
import uuid as uuid_module
from dataclasses import dataclass

import structlog

from easy_breezy.automation.scenarios import ScenarioNotFoundError, ScenarioService
from easy_breezy.core.bus import CommandBus, CommandError, CommandOutcome
from easy_breezy.core.model import DeltaError, StateDelta, state_to_dict
from easy_breezy.core.registry import DeviceRegistry
from easy_breezy.core.sensors import STALE_AFTER_SECONDS
from easy_breezy.core.state import StateCache
from easy_breezy.integrations.intents.model import (
    Catalog,
    CatalogDevice,
    CatalogScenario,
    CatalogSensor,
    Clarification,
    DeviceCommandIntent,
    ScenarioIntent,
    StatusIntent,
)
from easy_breezy.integrations.intents.rules import parse
from easy_breezy.storage import Database
from easy_breezy.storage.models import CommandSource, CommandStatus
from easy_breezy.storage.repos import DeviceRepo, RoomRepo, ScenarioRepo, SensorRepo

log = structlog.get_logger(__name__)

_MANUAL_PRIORITY = 0

_METRIC_LABELS = {
    "co2": ("CO₂", "ppm"),
    "temperature": ("температура", "°C"),
    "humidity": ("влажность", "%"),
}

_HELP_REPLY = (
    "Не понял. Примеры: «включи бризер в спальне», «поставь скорость три», "
    "«сделай 22 градуса», «какой CO₂ в детской», «ночной режим»."
)


@dataclass(frozen=True, slots=True)
class IntentReply:
    """Ответ на фразу: текст + исполнено ли что-то (FR-30/31)."""

    reply: str
    executed: bool
    intent: str | None
    """Вид распознанного интента (device_command|scenario|status) или None."""


class IntentService:
    def __init__(
        self,
        db: Database,
        registry: DeviceRegistry,
        cache: StateCache,
        bus: CommandBus,
        scenarios: ScenarioService,
        *,
        command_wait_seconds: float = 5.0,
    ) -> None:
        self._db = db
        self._registry = registry
        self._cache = cache
        self._bus = bus
        self._scenarios = scenarios
        self._wait = command_wait_seconds

    async def execute(self, text: str) -> IntentReply:
        catalog = await self._catalog()
        outcome = parse(text, catalog)
        log.info("intent_parsed", text=text, outcome=type(outcome).__name__)
        if outcome is None:
            return IntentReply(_HELP_REPLY, executed=False, intent=None)
        if isinstance(outcome, Clarification):
            return IntentReply(outcome.reply, executed=False, intent=None)
        if isinstance(outcome, ScenarioIntent):
            return await self._run_scenario(outcome)
        if isinstance(outcome, StatusIntent):
            return self._status_reply(outcome, catalog)
        return await self._run_command(outcome)

    # --- каталог ---------------------------------------------------------------

    async def _catalog(self) -> Catalog:
        now = time.time()
        async with self._db.session() as session:
            rooms = {room.id: room.name for room in await RoomRepo(session).list_all()}
            devices = [
                CatalogDevice(
                    device.uuid,
                    device.name,
                    rooms.get(device.room_id) if device.room_id else None,
                )
                for device in await DeviceRepo(session).list_active()
            ]
            scenarios = [
                CatalogScenario(record.id, record.name)
                for record in await ScenarioRepo(session).list_all()
            ]
            sensors = [
                CatalogSensor(
                    record.id,
                    record.name,
                    rooms.get(record.room_id) if record.room_id else None,
                    values=record.last_values or {},
                    stale=(
                        record.last_seen_at is None
                        or now - record.last_seen_at > STALE_AFTER_SECONDS
                    ),
                )
                for record in await SensorRepo(session).list_all()
            ]
        return Catalog(devices=devices, scenarios=scenarios, sensors=sensors)

    # --- исполнение ------------------------------------------------------------

    async def _run_command(self, intent: DeviceCommandIntent) -> IntentReply:
        try:
            delta = StateDelta.from_payload(intent.delta_payload)
        except DeltaError as exc:  # парсер собрал невалидное — это баг правил
            log.warning("intent_delta_invalid", error=str(exc))
            return IntentReply(_HELP_REPLY, executed=False, intent=None)

        run_id = uuid_module.uuid4().hex
        waiters: list[tuple[str, asyncio.Task[CommandOutcome | None]]] = []
        rejected: list[str] = []
        for device_uuid in intent.device_uuids:
            try:
                ticket = await self._bus.submit(
                    device_uuid=device_uuid,
                    delta=delta,
                    source=CommandSource.INTENT,
                    idempotency_key=f"intent:{run_id}:{device_uuid}",
                    priority=_MANUAL_PRIORITY,
                )
            except CommandError as exc:
                rejected.append(str(exc))
                continue
            waiters.append(
                (device_uuid, asyncio.create_task(self._outcome(ticket.outcome)))
            )

        done = 0
        pending = 0
        failed = 0
        for _device_uuid, waiter in waiters:
            outcome = await waiter
            if outcome is None:
                pending += 1
            elif outcome.status is CommandStatus.DONE:
                done += 1
            else:
                failed += 1

        summary = f"{intent.description} → {intent.target_label}"
        if done and not failed and not pending and not rejected:
            return IntentReply(
                f"Готово: {summary}.", executed=True, intent="device_command"
            )
        if done or pending:
            return IntentReply(
                f"Выполняю: {summary}.", executed=True, intent="device_command"
            )
        reason = rejected[0] if rejected else "устройство недоступно"
        return IntentReply(
            f"Не получилось: {reason}.", executed=False, intent="device_command"
        )

    async def _outcome(
        self, future: asyncio.Future[CommandOutcome]
    ) -> CommandOutcome | None:
        try:
            return await asyncio.wait_for(asyncio.shield(future), self._wait)
        except TimeoutError:
            return None

    async def _run_scenario(self, intent: ScenarioIntent) -> IntentReply:
        prefix = f"intent:{uuid_module.uuid4().hex}"
        try:
            submissions = await self._scenarios.run(
                intent.scenario_id,
                source=CommandSource.INTENT,
                idempotency_prefix=prefix,
                priority=_MANUAL_PRIORITY,
            )
        except ScenarioNotFoundError:
            return IntentReply(
                f"Сценарий «{intent.name}» не найден.", executed=False, intent=None
            )
        accepted = [entry for entry in submissions if entry.ticket is not None]
        if not accepted:
            return IntentReply(
                f"Сценарий «{intent.name}»: устройства недоступны.",
                executed=False,
                intent="scenario",
            )
        return IntentReply(
            f"Запускаю сценарий «{intent.name}».", executed=True, intent="scenario"
        )

    # --- статус ----------------------------------------------------------------

    def _status_reply(self, intent: StatusIntent, catalog: Catalog) -> IntentReply:
        lines: list[str] = []
        if intent.metric in (None, "co2", "humidity"):
            lines += self._sensor_lines(intent, catalog)
        if intent.metric in (None, "temperature"):
            lines += self._device_lines(intent, catalog)
            if intent.metric == "temperature" and not lines:
                lines += self._sensor_lines(intent, catalog)
        if not lines:
            where = f" в {intent.room}" if intent.room else ""
            return IntentReply(
                f"Пока нет данных{where}.", executed=False, intent="status"
            )
        return IntentReply("; ".join(lines) + ".", executed=False, intent="status")

    def _sensor_lines(self, intent: StatusIntent, catalog: Catalog) -> list[str]:
        lines = []
        for sensor in catalog.sensors:
            if intent.room is not None and sensor.room != intent.room:
                continue
            if sensor.stale or not sensor.values:
                continue
            metrics = (
                [intent.metric]
                if intent.metric in sensor.values
                else sorted(sensor.values) if intent.metric is None else []
            )
            parts = []
            for metric in metrics:
                label, unit = _METRIC_LABELS.get(metric, (metric, ""))
                parts.append(f"{label} {round(sensor.values[metric])} {unit}".strip())
            if parts:
                lines.append(f"{sensor.name}: {', '.join(parts)}")
        return lines

    def _device_lines(self, intent: StatusIntent, catalog: Catalog) -> list[str]:
        lines = []
        for device in catalog.devices:
            if intent.room is not None and device.room != intent.room:
                continue
            snapshot = self._cache.get(device.uuid)
            if snapshot is None or snapshot.state is None:
                continue
            state = state_to_dict(snapshot.state)
            if intent.metric == "temperature":
                lines.append(f"{device.name}: {state['out_temp']} °C")
            else:
                power = "работает" if state["power"] else "выключен"
                lines.append(
                    f"{device.name}: {power}, скорость {state['fan_speed']}, "
                    f"{state['out_temp']} °C"
                )
        return lines
