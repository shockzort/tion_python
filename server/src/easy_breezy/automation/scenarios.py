"""Сценарии: именованные списки действий без условий (план §9, FR-20).

Действие — цель (устройство или группа) плюс дельта состояния. Исполнение
идёт через командную шину: сценарий раскладывается в per-device дельты,
дельты одного устройства мержатся в порядке списка (позднее действие
переопределяет поля раннего) — одна команда на устройство, поля не теряются
(FR-5). Приоритет и hold-политику решает шина по источнику/приоритету.

Третий вид цели — триггер (``target_type="trigger"``, дельта
``{"enabled": bool}``): сценарий включает/выключает триггеры, что даёт
композицию «Расписание → Сценарий → Триггер» (ночной режим включает
свой maintain-триггер, дневной — свой). Рекурсия невозможна: включение
лишь взводит оценку будущих измерений датчика, синхронно ничего не
запускает. Toggles применяются ДО постановки device-команд.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

from easy_breezy.automation.maintain import KIND_MAINTAIN, disable_conflicting_maintain
from easy_breezy.core.bus import CommandBus, CommandError, CommandTicket
from easy_breezy.core.events import TOPIC_AUTOMATION_CHANGED, EventBus
from easy_breezy.core.model import DeltaError, StateDelta
from easy_breezy.storage import Database
from easy_breezy.storage.models import CommandSource
from easy_breezy.storage.repos import GroupRepo, ScenarioRepo, TriggerRepo

log = structlog.get_logger(__name__)

TARGET_DEVICE = "device"
TARGET_GROUP = "group"
TARGET_TRIGGER = "trigger"


class ScenarioError(Exception):
    """Сценарий не может быть исполнен (кривые действия, нет цели)."""


class ScenarioNotFoundError(ScenarioError):
    """Сценария нет в БД."""


@dataclass(frozen=True, slots=True)
class ActionSubmission:
    """Итог постановки per-device команды: квитанция или причина отказа."""

    device_uuid: str
    ticket: CommandTicket | None = None
    rejected: str | None = None


@dataclass(frozen=True, slots=True)
class _ResolvedActions:
    """Разложенные действия: per-device дельты + переключения триггеров."""

    deltas: dict[str, StateDelta] = field(default_factory=dict)
    toggles: list[tuple[int, bool]] = field(default_factory=list)


class ScenarioService:
    def __init__(self, db: Database, bus: CommandBus, events: EventBus) -> None:
        self._db = db
        self._bus = bus
        self._events = events

    async def run(
        self,
        scenario_id: int,
        *,
        source: CommandSource,
        idempotency_prefix: str,
        priority: int | None = None,
    ) -> list[ActionSubmission]:
        """Исполняет сценарий по id; повтор с тем же префиксом дедупится шиной."""
        async with self._db.session() as session:
            scenario = await ScenarioRepo(session).get(scenario_id)
        if scenario is None:
            raise ScenarioNotFoundError(f"сценарий {scenario_id} не найден")
        log.info(
            "scenario_run",
            scenario_id=scenario_id,
            name=scenario.name,
            source=source.value,
        )
        return await self.run_actions(
            scenario.actions,
            source=source,
            idempotency_prefix=idempotency_prefix,
            priority=priority,
        )

    async def run_actions(
        self,
        actions: list[Any],
        *,
        source: CommandSource,
        idempotency_prefix: str,
        priority: int | None = None,
    ) -> list[ActionSubmission]:
        """Исполняет список действий (сценарий или inline-действия расписания)."""
        resolved = await self._resolve(actions)
        if resolved.toggles:
            await self._apply_trigger_toggles(resolved.toggles)
        submissions: list[ActionSubmission] = []
        for device_uuid, delta in resolved.deltas.items():
            try:
                ticket = await self._bus.submit(
                    device_uuid=device_uuid,
                    delta=delta,
                    source=source,
                    idempotency_key=f"{idempotency_prefix}:{device_uuid}",
                    priority=priority,
                )
            except CommandError as exc:
                log.warning(
                    "scenario_action_rejected",
                    device_uuid=device_uuid,
                    error=str(exc),
                )
                submissions.append(ActionSubmission(device_uuid, rejected=str(exc)))
            else:
                submissions.append(ActionSubmission(device_uuid, ticket=ticket))
        return submissions

    async def _resolve(self, actions: list[Any]) -> _ResolvedActions:
        """Раскладывает действия в per-device дельты (мерж по порядку) и toggles."""
        merged: dict[str, dict[str, Any]] = {}
        toggles: list[tuple[int, bool]] = []
        async with self._db.session() as session:
            groups = GroupRepo(session)
            for index, action in enumerate(actions):
                if not isinstance(action, dict):
                    raise ScenarioError(f"действие {index}: не объект")
                target_type = action.get("target_type")
                target_id = action.get("target_id")
                payload = action.get("delta")
                if target_id is None or not isinstance(payload, dict):
                    raise ScenarioError(f"действие {index}: нет target_id или delta")
                if target_type == TARGET_TRIGGER:
                    enabled = payload.get("enabled")
                    if not isinstance(enabled, bool):
                        raise ScenarioError(
                            f"действие {index}: для триггера delta —"
                            " {'enabled': bool}"
                        )
                    toggles.append((int(target_id), enabled))
                    continue
                if target_type == TARGET_DEVICE:
                    device_uuids = [str(target_id)]
                elif target_type == TARGET_GROUP:
                    device_uuids = await groups.members(int(target_id))
                    if not device_uuids:
                        log.warning(
                            "scenario_group_empty", index=index, group_id=target_id
                        )
                else:
                    raise ScenarioError(
                        f"действие {index}: target_type {target_type!r} неизвестен"
                    )
                for device_uuid in device_uuids:
                    merged.setdefault(device_uuid, {}).update(payload)
        try:
            deltas = {
                device_uuid: StateDelta.from_payload(payload)
                for device_uuid, payload in merged.items()
            }
        except DeltaError as exc:
            raise ScenarioError(str(exc)) from exc
        return _ResolvedActions(deltas=deltas, toggles=toggles)

    async def _apply_trigger_toggles(self, toggles: list[tuple[int, bool]]) -> None:
        """Включает/выключает триггеры; защёлка сбрасывается без exit-действий.

        Включение обнуляет ``last_fired_at`` (реакция на следующее же
        измерение) и снимает конфликтующие maintain-триггеры
        (радиокнопочная семантика). Отсутствующий триггер — warning,
        остальные действия сценария исполняются.
        """
        changed: list[int] = []
        async with self._db.session() as session:
            repo = TriggerRepo(session)
            for trigger_id, enabled in toggles:
                trigger = await repo.get(trigger_id)
                if trigger is None:
                    log.warning("scenario_trigger_missing", trigger_id=trigger_id)
                    continue
                trigger.enabled = enabled
                trigger.is_active = False
                if enabled:
                    trigger.last_fired_at = None
                    if trigger.kind == KIND_MAINTAIN:
                        changed.extend(
                            await disable_conflicting_maintain(session, trigger)
                        )
                changed.append(trigger_id)
                log.info(
                    "scenario_trigger_toggled",
                    trigger_id=trigger_id,
                    enabled=enabled,
                )
        for trigger_id in changed:
            self._events.publish(
                TOPIC_AUTOMATION_CHANGED,
                {"kind": "trigger", "action": "updated", "id": trigger_id},
            )
