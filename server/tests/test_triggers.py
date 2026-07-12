"""Триггеры: табличные тесты защёлки + e2e движка на фейках (FR-22/23)."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from easy_breezy.automation.scenarios import ScenarioService
from easy_breezy.automation.triggers import (
    TriggerDecision,
    TriggerEngine,
    decide,
    in_window,
)
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.events import TOPIC_COMMAND_FINISHED
from easy_breezy.core.sensors import SensorIngest
from easy_breezy.storage.models import Device, Trigger
from easy_breezy.storage.repos import SensorRepo, TriggerRepo
from tests.conftest import CoreEnv, FakeClock, wait_for_condition

MSK = ZoneInfo("Europe/Moscow")

NOON = datetime(2026, 7, 12, 12, 0, tzinfo=MSK).timestamp()


def make_trigger(**overrides: Any) -> Trigger:
    """Триггер «CO₂ > 1000, гистерезис 200» — незакреплённый ORM-объект."""
    fields: dict[str, Any] = {
        "name": "CO₂ высокий",
        "sensor_id": 1,
        "metric": "co2",
        "op": ">",
        "threshold": 1000.0,
        "hysteresis": 200.0,
        "cooldown_s": 0,
        "window_start": None,
        "window_end": None,
        "enabled": True,
        "is_active": False,
        "last_fired_at": None,
    }
    fields.update(overrides)
    return Trigger(**fields)


# --- decide: таблица переходов защёлки ---------------------------------------


@pytest.mark.parametrize(
    ("value", "is_active", "expected"),
    [
        (900, False, None),  # ниже порога, спим
        (1000, False, None),  # порог строгий
        (1001, False, TriggerDecision("enter", True)),
        (1500, True, None),  # уже активен — не повторяем
        (900, True, None),  # внутри гистерезиса (800..1000) — держим
        (800, True, None),  # граница гистерезиса строгая
        (799, True, TriggerDecision("exit", False)),
    ],
)
def test_latch_greater(
    value: float, is_active: bool, expected: TriggerDecision | None
) -> None:
    trigger = make_trigger(is_active=is_active)
    assert decide(trigger, value, NOON, tz=MSK) == expected


@pytest.mark.parametrize(
    ("value", "is_active", "expected"),
    [
        (25, False, None),
        (19, False, TriggerDecision("enter", True)),
        (20.5, True, None),  # 20 + 1 гистерезис
        (21.1, True, TriggerDecision("exit", False)),
    ],
)
def test_latch_less(
    value: float, is_active: bool, expected: TriggerDecision | None
) -> None:
    trigger = make_trigger(
        metric="temperature",
        op="<",
        threshold=20.0,
        hysteresis=1.0,
        is_active=is_active,
    )
    assert decide(trigger, value, NOON, tz=MSK) == expected


def test_cooldown_blocks_reenter() -> None:
    """Повторный enter раньше кулдауна не срабатывает, после — срабатывает."""
    trigger = make_trigger(cooldown_s=300, last_fired_at=int(NOON) - 100)
    assert decide(trigger, 1200, NOON, tz=MSK) is None
    trigger_rested = make_trigger(cooldown_s=300, last_fired_at=int(NOON) - 301)
    assert decide(trigger_rested, 1200, NOON, tz=MSK) == TriggerDecision("enter", True)


def test_window_gates_enter_but_not_exit() -> None:
    """Вне окна вход закрыт; выход (возврат к норме) разрешён всегда."""
    trigger = make_trigger(window_start="08:00", window_end="22:00")
    night = datetime(2026, 7, 12, 23, 30, tzinfo=MSK).timestamp()
    assert decide(trigger, 1500, night, tz=MSK) is None
    assert decide(trigger, 1500, NOON, tz=MSK) == TriggerDecision("enter", True)

    active_night = make_trigger(
        window_start="08:00", window_end="22:00", is_active=True
    )
    assert decide(active_night, 700, night, tz=MSK) == TriggerDecision("exit", False)


def test_window_across_midnight() -> None:
    assert in_window("22:00", "06:00", NOON, MSK) is False
    night = datetime(2026, 7, 12, 23, 30, tzinfo=MSK).timestamp()
    morning = datetime(2026, 7, 12, 5, 59, tzinfo=MSK).timestamp()
    late_morning = datetime(2026, 7, 12, 6, 0, tzinfo=MSK).timestamp()
    assert in_window("22:00", "06:00", night, MSK) is True
    assert in_window("22:00", "06:00", morning, MSK) is True
    assert in_window("22:00", "06:00", late_morning, MSK) is False
    assert in_window(None, None, NOON, MSK) is True


# --- движок на фейках ----------------------------------------------------------


async def engine_env(
    core: CoreEnv,
) -> tuple[TriggerEngine, SensorIngest, Device, int]:
    """Бризер + датчик + движок; возвращает (движок, ingest, device, sensor_id)."""
    device = await core.registry.add_device(mac="FA:KE:00:00:00:01", name="Тест")
    await wait_for_condition(
        lambda: core.registry.connection(device.uuid) is ConnectionState.ONLINE
    )
    clock = FakeClock(NOON)
    # ingest и движок живут на одних часах — иначе sweep/кулдаун считают
    # от разных эпох
    ingest = SensorIngest(core.db, core.events, now=clock.now)
    async with core.db.session() as session:
        sensor = await SensorRepo(session).create(
            kind="mqtt", name="CO₂ спальня", source_key="home/air"
        )
        sensor_id = sensor.id
    scenarios = ScenarioService(core.db, core.bus, core.events)
    engine = TriggerEngine(
        core.db,
        scenarios,
        core.events,
        clock,
        cache=core.cache,
        holds=core.holds,
        tz=MSK,
    )
    return engine, ingest, device, sensor_id


def turbo_trigger_fields(sensor_id: int, device_uuid: str) -> dict[str, Any]:
    return {
        "name": "CO₂ турбо",
        "sensor_id": sensor_id,
        "metric": "co2",
        "op": ">",
        "threshold": 1000.0,
        "hysteresis": 200.0,
        "cooldown_s": 0,
        "enter_actions": [
            {
                "target_type": "device",
                "target_id": device_uuid,
                "delta": {"fan_speed": 6},
            }
        ],
        "exit_actions": [
            {
                "target_type": "device",
                "target_id": device_uuid,
                "delta": {"fan_speed": 2},
            }
        ],
    }


async def test_engine_enter_and_exit_commands(core: CoreEnv) -> None:
    """Надышали CO₂ — турбо; проветрили — возврат (гейт фазы)."""
    engine, ingest, device, sensor_id = await engine_env(core)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **turbo_trigger_fields(sensor_id, device.uuid)
        )
    await engine.start()
    try:
        with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
            await ingest.ingest(
                kind="mqtt", source_key="home/air", metrics={"co2": 1250}
            )
            enter_event = await asyncio.wait_for(sub.get(), 5)
            assert enter_event.data["status"] == "done"
            assert enter_event.data["result_state"]["fan_speed"] == 6

            # внутри гистерезиса — тишина, повторных команд нет
            await ingest.ingest(
                kind="mqtt", source_key="home/air", metrics={"co2": 900}
            )
            # ниже порог − гистерезис — выход
            await ingest.ingest(
                kind="mqtt", source_key="home/air", metrics={"co2": 750}
            )
            exit_event = await asyncio.wait_for(sub.get(), 5)
            assert exit_event.data["status"] == "done"
            assert exit_event.data["result_state"]["fan_speed"] == 2

        async with core.db.session() as session:
            trigger = (await TriggerRepo(session).list_all())[0]
            assert trigger.is_active is False
            assert trigger.last_fired_at == int(NOON)
    finally:
        await engine.stop()


async def test_engine_respects_manual_hold(core: CoreEnv) -> None:
    """Manual-hold: команда триггера честно пропускается (FR-23)."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **turbo_trigger_fields(sensor_id, device.uuid)
        )
    core.holds.place(device.uuid)
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        fired = await engine.evaluate(sensor_id, {"co2": 1500}, NOON)
        assert fired == 1
        event = await asyncio.wait_for(sub.get(), 5)
    assert event.data["status"] == "skipped_hold"


async def test_engine_scenario_reference(core: CoreEnv) -> None:
    """Триггер может запускать сценарий вместо inline-действий."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    from easy_breezy.storage.repos import ScenarioRepo

    async with core.db.session() as session:
        scenario = await ScenarioRepo(session).create(
            name="Турбо",
            actions=[
                {
                    "target_type": "device",
                    "target_id": device.uuid,
                    "delta": {"fan_speed": 5},
                }
            ],
        )
        await TriggerRepo(session).create(
            name="CO₂ сценарий",
            sensor_id=sensor_id,
            metric="co2",
            op=">",
            threshold=800.0,
            enter_scenario_id=scenario.id,
        )
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        assert await engine.evaluate(sensor_id, {"co2": 900}, NOON) == 1
        event = await asyncio.wait_for(sub.get(), 5)
    assert event.data["result_state"]["fan_speed"] == 5
    # журнал: источник trigger, приоритет 1 — обгоняет расписание
    from sqlalchemy import select

    from easy_breezy.storage.models import CommandRecord

    async with core.db.session() as session:
        record = (await session.execute(select(CommandRecord))).scalars().one()
    assert record.source == "trigger"
    assert record.priority == 1


async def test_engine_idempotent_same_measurement(core: CoreEnv) -> None:
    """Повторная оценка того же измерения не дублирует команду (дедуп ключа)."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **turbo_trigger_fields(sensor_id, device.uuid)
        )
    assert await engine.evaluate(sensor_id, {"co2": 1500}, NOON) == 1
    # защёлку «откатили» (симуляция падения после submit до commit)
    async with core.db.session() as session:
        trigger = (await TriggerRepo(session).list_all())[0]
        trigger.is_active = False
    assert await engine.evaluate(sensor_id, {"co2": 1500}, NOON) == 1

    from sqlalchemy import func, select

    from easy_breezy.storage.models import CommandRecord

    await wait_for_condition(lambda: True)  # дать воркеру шины дожевать
    async with core.db.session() as session:
        count = (
            await session.execute(select(func.count(CommandRecord.id)))
        ).scalar_one()
    assert count == 1  # тот же ключ trigger:{id}:enter:{ts} — команда одна


# --- maintain: поддержание CO₂ --------------------------------------------------


def maintain_trigger_fields(
    sensor_id: int, device_uuid: str, **overrides: Any
) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "name": "CO₂ поддержание",
        "sensor_id": sensor_id,
        "metric": "co2",
        "kind": "maintain",
        "op": ">",
        "threshold": 1000.0,
        "hysteresis": 50.0,
        "cooldown_s": 120,
        "speed_min": 1,
        "speed_max": 6,
        "enabled": True,
    }
    fields.update(overrides)
    fields.setdefault("targets", [{"target_type": "device", "target_id": device_uuid}])
    return fields


async def wait_state_cached(core: CoreEnv, device_uuid: str) -> None:
    await wait_for_condition(
        lambda: (snapshot := core.cache.get(device_uuid)) is not None
        and snapshot.state is not None
    )


async def test_maintain_steps_speed_and_journal(core: CoreEnv) -> None:
    """CO₂ выше цели — ступень вверх; журнал: source=trigger, priority=1."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    await wait_state_cached(core, device.uuid)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **maintain_trigger_fields(sensor_id, device.uuid)
        )
    # фейк стартует с fan_speed=2; ошибка 100 ≥ 2×50 — шаг +2
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        assert await engine.evaluate(sensor_id, {"co2": 1100}, NOON) == 1
        event = await asyncio.wait_for(sub.get(), 5)
    assert event.data["status"] == "done"
    assert event.data["result_state"]["fan_speed"] == 4

    from sqlalchemy import select

    from easy_breezy.storage.models import CommandRecord

    async with core.db.session() as session:
        record = (await session.execute(select(CommandRecord))).scalars().one()
        trigger = (await TriggerRepo(session).list_all())[0]
    assert record.source == "trigger"
    assert record.priority == 1
    assert trigger.last_fired_at == int(NOON)


async def test_maintain_cooldown_gates_adjustments(core: CoreEnv) -> None:
    """Вторая корректировка не раньше кулдауна."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    await wait_state_cached(core, device.uuid)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **maintain_trigger_fields(sensor_id, device.uuid)
        )
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        assert await engine.evaluate(sensor_id, {"co2": 1100}, NOON) == 1
        await asyncio.wait_for(sub.get(), 5)
    await wait_for_condition(
        lambda: (snap := core.cache.get(device.uuid)) is not None
        and snap.state is not None
        and snap.state.fan_speed == 4
    )
    assert await engine.evaluate(sensor_id, {"co2": 1100}, NOON + 60) == 0
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        assert await engine.evaluate(sensor_id, {"co2": 1100}, NOON + 121) == 1
        event = await asyncio.wait_for(sub.get(), 5)
    assert event.data["result_state"]["fan_speed"] == 6


async def test_maintain_hold_skips_without_burning_cooldown(core: CoreEnv) -> None:
    """Под manual-hold — ни команды, ни записи в журнал, кулдаун цел."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    await wait_state_cached(core, device.uuid)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **maintain_trigger_fields(sensor_id, device.uuid)
        )
    core.holds.place(device.uuid)
    assert await engine.evaluate(sensor_id, {"co2": 1500}, NOON) == 0
    assert await journal_is_empty(core)
    async with core.db.session() as session:
        trigger = (await TriggerRepo(session).list_all())[0]
        assert trigger.last_fired_at is None

    # hold снят — регулирование продолжается сразу, без ожидания кулдауна
    core.holds.release(device.uuid)
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        assert await engine.evaluate(sensor_id, {"co2": 1500}, NOON + 1) == 1
        event = await asyncio.wait_for(sub.get(), 5)
    assert event.data["status"] == "done"


async def journal_is_empty(core: CoreEnv) -> bool:
    from sqlalchemy import func, select

    from easy_breezy.storage.models import CommandRecord

    async with core.db.session() as session:
        count = (
            await session.execute(select(func.count(CommandRecord.id)))
        ).scalar_one()
    return count == 0


async def test_maintain_skips_unknown_and_offline_devices(core: CoreEnv) -> None:
    """Нет снапшота/офлайн — корректировка пропускается молча."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    await wait_state_cached(core, device.uuid)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **maintain_trigger_fields(
                sensor_id,
                device.uuid,
                targets=[{"target_type": "device", "target_id": "нет-такого"}],
            )
        )
    assert await engine.evaluate(sensor_id, {"co2": 1500}, NOON) == 0
    assert await journal_is_empty(core)


async def test_maintain_window_gates_regulation(core: CoreEnv) -> None:
    """Вне окна регулятор молчит."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    await wait_state_cached(core, device.uuid)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **maintain_trigger_fields(
                sensor_id,
                device.uuid,
                window_start="23:00",
                window_end="09:00",
            )
        )
    assert await engine.evaluate(sensor_id, {"co2": 1500}, NOON) == 0
    night = datetime(2026, 7, 12, 23, 30, tzinfo=MSK).timestamp()
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        assert await engine.evaluate(sensor_id, {"co2": 1500}, night) == 1
        await asyncio.wait_for(sub.get(), 5)


async def test_maintain_group_targets(core: CoreEnv) -> None:
    """Цель-группа раскрывается в устройства."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    await wait_state_cached(core, device.uuid)
    from easy_breezy.storage.repos import GroupRepo

    async with core.db.session() as session:
        groups = GroupRepo(session)
        group = await groups.create("Все бризеры")
        await groups.set_members(group.id, [device.uuid])
        await TriggerRepo(session).create(
            **maintain_trigger_fields(
                sensor_id,
                device.uuid,
                targets=[{"target_type": "group", "target_id": group.id}],
            )
        )
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        assert await engine.evaluate(sensor_id, {"co2": 1100}, NOON) == 1
        event = await asyncio.wait_for(sub.get(), 5)
    assert event.data["result_state"]["fan_speed"] == 4


async def test_maintain_idempotent_same_measurement(core: CoreEnv) -> None:
    """Повторная оценка того же измерения не дублирует команду."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    await wait_state_cached(core, device.uuid)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **maintain_trigger_fields(sensor_id, device.uuid, cooldown_s=0)
        )
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        assert await engine.evaluate(sensor_id, {"co2": 1100}, NOON) == 1
        await asyncio.wait_for(sub.get(), 5)
    # состояние в кэше могло не успеть обновиться — но ключ идемпотентности
    # trigger:{id}:maintain:{ts}:{uuid} дедупит повтор на шине
    await engine.evaluate(sensor_id, {"co2": 1100}, NOON)

    from sqlalchemy import func, select

    from easy_breezy.storage.models import CommandRecord

    async with core.db.session() as session:
        count = (
            await session.execute(select(func.count(CommandRecord.id)))
        ).scalar_one()
    assert count == 1


async def test_maintain_converges_to_power_off(core: CoreEnv) -> None:
    """speed_min=0: при низком CO₂ регулятор доводит бризер до выключения."""
    engine, _ingest, device, sensor_id = await engine_env(core)
    await wait_state_cached(core, device.uuid)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **maintain_trigger_fields(sensor_id, device.uuid, speed_min=0)
        )
    ts = NOON
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        for _ in range(4):  # fan 2 → 1 → off (с запасом)
            snapshot = core.cache.get(device.uuid)
            assert snapshot is not None and snapshot.state is not None
            if not snapshot.state.power:
                break
            assert await engine.evaluate(sensor_id, {"co2": 900}, ts) == 1
            ts += 121
            event = await asyncio.wait_for(sub.get(), 5)
            assert event.data["status"] == "done"
            expected = event.data["result_state"]

            def cache_caught_up(want: dict[str, Any] = expected) -> bool:
                snap = core.cache.get(device.uuid)
                return (
                    snap is not None
                    and snap.state is not None
                    and snap.state.power == want["power"]
                    and snap.state.fan_speed == want["fan_speed"]
                )

            await wait_for_condition(cache_caught_up)
    final = core.cache.get(device.uuid)
    assert final is not None and final.state is not None
    assert final.state.power is False
    # выключен и CO₂ низкий — больше не трогаем
    assert await engine.evaluate(sensor_id, {"co2": 900}, ts + 121) == 0


async def test_maintain_in_deadband_silent(core: CoreEnv) -> None:
    engine, _ingest, device, sensor_id = await engine_env(core)
    await wait_state_cached(core, device.uuid)
    async with core.db.session() as session:
        await TriggerRepo(session).create(
            **maintain_trigger_fields(sensor_id, device.uuid)
        )
    assert await engine.evaluate(sensor_id, {"co2": 1000}, NOON) == 0
    assert await journal_is_empty(core)


async def test_sweep_warns_once_for_silent_sensor(core: CoreEnv) -> None:
    engine, ingest, _device, sensor_id = await engine_env(core)
    # датчик никогда не слал данных — молчит
    await engine.run_sweep()
    assert sensor_id in engine._silent_ids
    await engine.run_sweep()  # второй проход не дублирует warning (набор тот же)
    assert sensor_id in engine._silent_ids
    # данные пришли — датчик жив, отметка снята
    await ingest.ingest(kind="mqtt", source_key="home/air", metrics={"co2": 600})
    await engine.run_sweep()
    assert sensor_id not in engine._silent_ids
