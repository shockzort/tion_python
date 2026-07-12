"""Поддержание CO₂: чистый регулятор скорости и семантика целей.

Регулятор ступенчатый: одна корректировка на измерение (кулдаун гасит
дребезг), шаг ±1, при ошибке ≥ ``STRONG_FACTOR`` × зоны покоя — ±2.
Зона покоя (deadband) вокруг цели — тишина. При ``speed_min == 0``
регулятору разрешено выключать бризер, но только с минимальной рабочей
скорости (не прыжком с высокой) — и включать обратно при росте CO₂.

Сходимость при каденсе датчика ~1/мин и кулдауне 120 с: от «выключен»
до 6-й скорости ~8–10 минут — сопоставимо с автоматикой MagicAir.

Функция ``decide_speed`` чистая (без I/O), тестируется таблично.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.ble.protocol.s4 import FAN_SPEED_MIN
from easy_breezy.core.model import StateDelta
from easy_breezy.storage.models import Trigger
from easy_breezy.storage.repos import GroupRepo, TriggerRepo

KIND_THRESHOLD = "threshold"
KIND_MAINTAIN = "maintain"

SPEED_FLOOR_ALLOWED = 0
"""Минимально допустимый speed_min (0 — разрешено выключение питания)."""

DEFAULT_DEADBAND = 50.0
"""Зона покоя по умолчанию, ppm."""

DEFAULT_COOLDOWN_S = 120
"""Минимум секунд между корректировками по умолчанию."""

STRONG_FACTOR = 2.0
"""Ошибка ≥ STRONG_FACTOR × deadband — шаг 2 вместо 1."""


def decide_speed(
    *,
    value: float,
    target: float,
    deadband: float,
    current_speed: int,
    power_on: bool,
    speed_min: int,
    speed_max: int,
) -> StateDelta | None:
    """Одна корректировка регулятора; None — ничего не менять.

    ``floor`` — минимальная рабочая скорость (1 даже при speed_min=0:
    ноль означает «можно выключить», а не «скорость 0»).
    """
    floor = max(speed_min, FAN_SPEED_MIN)
    error = value - target

    if error > deadband:
        step = 2 if error >= STRONG_FACTOR * deadband else 1
        if not power_on:
            speed = min(max(floor + step - 1, floor), speed_max)
            return StateDelta(power=True, fan_speed=speed)
        new_speed = min(max(current_speed + step, floor), speed_max)
        if new_speed == current_speed:
            return None
        return StateDelta(fan_speed=new_speed)

    if error < -deadband:
        if not power_on:
            return None
        step = 2 if -error >= STRONG_FACTOR * deadband else 1
        new_speed = current_speed - step
        if new_speed < floor:
            if speed_min == 0 and current_speed <= floor:
                return StateDelta(power=False)
            new_speed = floor
        if new_speed == current_speed:
            return None
        return StateDelta(fan_speed=new_speed)

    return None


async def expand_targets(session: AsyncSession, targets: list[Any] | None) -> set[str]:
    """Раскрывает цели maintain-триггера в множество uuid устройств."""
    uuids: set[str] = set()
    groups = GroupRepo(session)
    for entry in targets or []:
        if not isinstance(entry, dict):
            continue
        target_id = entry.get("target_id")
        if target_id is None:
            continue
        if entry.get("target_type") == "group":
            uuids.update(await groups.members(int(target_id)))
        else:
            uuids.add(str(target_id))
    return uuids


async def disable_conflicting_maintain(
    session: AsyncSession, trigger: Trigger
) -> list[int]:
    """Выключает другие maintain-триггеры с пересекающимися устройствами.

    Радиокнопочная семантика: на устройстве активен максимум один
    регулятор — включение нового снимает старый (ночной/дневной режимы
    сменяют друг друга одним действием сценария). Возвращает id
    выключенных триггеров (вызывающий публикует ``automation.changed``).
    """
    own = await expand_targets(session, trigger.targets)
    disabled: list[int] = []
    for other in await TriggerRepo(session).list_enabled_maintain():
        if other.id == trigger.id:
            continue
        if own & await expand_targets(session, other.targets):
            other.enabled = False
            other.is_active = False
            disabled.append(other.id)
    return disabled
