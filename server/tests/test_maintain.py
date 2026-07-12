"""Регулятор поддержания CO₂: табличные тесты decide_speed + цели."""

from __future__ import annotations

import time
from typing import Any

import pytest

from easy_breezy.automation.maintain import (
    decide_speed,
    disable_conflicting_maintain,
    expand_targets,
)
from easy_breezy.core.model import StateDelta
from easy_breezy.storage import Database
from easy_breezy.storage.models import Trigger
from easy_breezy.storage.repos import (
    DeviceRepo,
    GroupRepo,
    SensorRepo,
    TriggerRepo,
)

# --- decide_speed: таблица корректировок --------------------------------------
# Базовый случай: цель 1000, зона покоя 50, диапазон 0..6 (если не указано).


@pytest.mark.parametrize(
    ("value", "current", "power_on", "speed_min", "speed_max", "expected"),
    [
        # зона покоя — тишина (границы включительно)
        (1000, 3, True, 0, 6, None),
        (1050, 3, True, 0, 6, None),
        (950, 3, True, 0, 6, None),
        # выше цели: +1, при ошибке ≥ 2×зоны — +2
        (1051, 3, True, 0, 6, StateDelta(fan_speed=4)),
        (1099, 3, True, 0, 6, StateDelta(fan_speed=4)),
        (1100, 3, True, 0, 6, StateDelta(fan_speed=5)),
        # клампы сверху
        (1300, 6, True, 0, 6, None),
        (1300, 5, True, 0, 6, StateDelta(fan_speed=6)),
        (1300, 2, True, 0, 4, StateDelta(fan_speed=4)),
        # пробуждение: с floor (или floor+1 при сильной ошибке)
        (1051, 0, False, 0, 6, StateDelta(power=True, fan_speed=1)),
        (1100, 0, False, 0, 6, StateDelta(power=True, fan_speed=2)),
        (1051, 0, False, 2, 6, StateDelta(power=True, fan_speed=2)),
        (1100, 0, False, 6, 6, StateDelta(power=True, fan_speed=6)),
        # ниже цели: −1 / −2
        (949, 3, True, 0, 6, StateDelta(fan_speed=2)),
        (900, 4, True, 0, 6, StateDelta(fan_speed=2)),
        # floor держит скорость при speed_min >= 1
        (900, 3, True, 2, 6, StateDelta(fan_speed=2)),
        (900, 2, True, 2, 6, None),
        # выключение только с минимальной рабочей скорости
        (949, 1, True, 0, 6, StateDelta(power=False)),
        (900, 2, True, 0, 6, StateDelta(fan_speed=1)),  # не прыжком 2→off
        # выключен и свежо/в зоне — не трогаем
        (900, 0, False, 0, 6, None),
        (1000, 0, False, 0, 6, None),
        # текущая скорость ниже floor — подтяжка в диапазон при росте CO₂
        (1051, 1, True, 3, 6, StateDelta(fan_speed=3)),
    ],
)
def test_decide_speed(
    value: float,
    current: int,
    power_on: bool,
    speed_min: int,
    speed_max: int,
    expected: StateDelta | None,
) -> None:
    result = decide_speed(
        value=value,
        target=1000.0,
        deadband=50.0,
        current_speed=current,
        power_on=power_on,
        speed_min=speed_min,
        speed_max=speed_max,
    )
    assert result == expected


# --- expand_targets / disable_conflicting_maintain -----------------------------


async def _make_maintain(
    db: Database, *, name: str, sensor_id: int, targets: list[dict[str, Any]]
) -> int:
    async with db.session() as session:
        trigger = await TriggerRepo(session).create(
            name=name,
            sensor_id=sensor_id,
            metric="co2",
            kind="maintain",
            op=">",
            threshold=1000.0,
            hysteresis=50.0,
            cooldown_s=120,
            speed_min=1,
            speed_max=6,
            targets=targets,
            enabled=True,
        )
        return trigger.id


async def test_expand_and_conflicts(db: Database) -> None:
    """Группы раскрываются; включение нового регулятора снимает пересекающийся."""
    now = int(time.time())
    async with db.session() as session:
        devices = DeviceRepo(session)
        dev_a = await devices.create(mac="AA:00:00:00:00:01", name="A", created_at=now)
        dev_b = await devices.create(mac="AA:00:00:00:00:02", name="B", created_at=now)
        dev_c = await devices.create(mac="AA:00:00:00:00:03", name="C", created_at=now)
        groups = GroupRepo(session)
        group = await groups.create("Спальня")
        await groups.set_members(group.id, [dev_b.uuid])
        sensor = await SensorRepo(session).create(
            kind="mqtt", name="CO₂", source_key="home/air"
        )
        sensor_id = sensor.id
        group_id = group.id

    async with db.session() as session:
        expanded = await expand_targets(
            session,
            [
                {"target_type": "device", "target_id": dev_a.uuid},
                {"target_type": "group", "target_id": group_id},
            ],
        )
        assert expanded == {dev_a.uuid, dev_b.uuid}
        assert await expand_targets(session, None) == set()

    # старый регулятор пересекается с новым через группу — выключается
    old_id = await _make_maintain(
        db,
        name="Старый",
        sensor_id=sensor_id,
        targets=[{"target_type": "device", "target_id": dev_b.uuid}],
    )
    # независимый регулятор на другом устройстве — не трогается
    other_id = await _make_maintain(
        db,
        name="Сторонний",
        sensor_id=sensor_id,
        targets=[{"target_type": "device", "target_id": dev_c.uuid}],
    )
    new_id = await _make_maintain(
        db,
        name="Новый",
        sensor_id=sensor_id,
        targets=[{"target_type": "group", "target_id": group_id}],
    )

    async with db.session() as session:
        repo = TriggerRepo(session)
        new_trigger = await repo.get(new_id)
        assert new_trigger is not None
        disabled = await disable_conflicting_maintain(session, new_trigger)
        assert disabled == [old_id]

    async with db.session() as session:
        repo = TriggerRepo(session)

        async def enabled_of(trigger_id: int) -> bool:
            record: Trigger | None = await repo.get(trigger_id)
            assert record is not None
            return record.enabled

        assert await enabled_of(old_id) is False
        assert await enabled_of(other_id) is True
        assert await enabled_of(new_id) is True
