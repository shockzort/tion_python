"""Сценарии: именованные списки действий без условий (план §9, FR-20).

Действие — цель (устройство или группа) плюс дельта состояния. Исполнение
идёт через командную шину: сценарий раскладывается в per-device дельты,
дельты одного устройства мержатся в порядке списка (позднее действие
переопределяет поля раннего) — одна команда на устройство, поля не теряются
(FR-5). Приоритет и hold-политику решает шина по источнику/приоритету.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from easy_breezy.core.bus import CommandBus, CommandError, CommandTicket
from easy_breezy.core.model import DeltaError, StateDelta
from easy_breezy.storage import Database
from easy_breezy.storage.models import CommandSource
from easy_breezy.storage.repos import GroupRepo, ScenarioRepo

log = structlog.get_logger(__name__)

TARGET_DEVICE = "device"
TARGET_GROUP = "group"


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


class ScenarioService:
    def __init__(self, db: Database, bus: CommandBus) -> None:
        self._db = db
        self._bus = bus

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
        deltas = await self._resolve(actions)
        submissions: list[ActionSubmission] = []
        for device_uuid, delta in deltas.items():
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

    async def _resolve(self, actions: list[Any]) -> dict[str, StateDelta]:
        """Раскладывает действия в per-device дельты с мержем по порядку."""
        merged: dict[str, dict[str, Any]] = {}
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
            return {
                device_uuid: StateDelta.from_payload(payload)
                for device_uuid, payload in merged.items()
            }
        except DeltaError as exc:
            raise ScenarioError(str(exc)) from exc
