"""Автоматизация: сценарии, планировщик, time-travel (план §9, Фаза 5).

Время — только FakeClock; cron-семантика фиксируется по фактическому
поведению croniter (включая переходы DST, проверено пробой на Europe/Berlin).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select

from easy_breezy.automation.scenarios import (
    ScenarioNotFoundError,
    ScenarioService,
)
from easy_breezy.automation.scheduler import SchedulerService, validate_cron
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.events import (
    TOPIC_AUTOMATION_CHANGED,
    TOPIC_COMMAND_FINISHED,
)
from easy_breezy.storage.models import CommandRecord, CommandSource, Device
from easy_breezy.storage.repos import GroupRepo, ScenarioRepo, ScheduleRepo
from tests.conftest import CoreEnv, FakeClock, wait_for_condition

MSK = ZoneInfo("Europe/Moscow")
BERLIN = ZoneInfo("Europe/Berlin")


def msk(*args: int) -> float:
    return datetime(*args, tzinfo=MSK).timestamp()  # type: ignore[arg-type]


@dataclass
class AutomationEnv:
    scenarios: ScenarioService
    scheduler: SchedulerService
    clock: FakeClock


START = msk(2026, 7, 12, 22, 59)


@pytest.fixture
async def automation(core: CoreEnv) -> AutomationEnv:
    clock = FakeClock(START)
    scenarios = ScenarioService(core.db, core.bus, core.events)
    scheduler = SchedulerService(core.db, scenarios, core.events, clock, tz=MSK)
    return AutomationEnv(scenarios, scheduler, clock)


async def add_devices(core: CoreEnv, count: int) -> list[Device]:
    devices = []
    for index in range(1, count + 1):
        added = await core.registry.add_device(
            mac=f"FA:KE:00:00:00:0{index}", name=f"Бризер {index}"
        )
        devices.append(added)
    await wait_for_condition(
        lambda: all(
            core.registry.connection(device.uuid) is ConnectionState.ONLINE
            for device in devices
        )
    )
    return devices


async def make_scenario(core: CoreEnv, name: str, actions: list[Any]) -> int:
    async with core.db.session() as session:
        record = await ScenarioRepo(session).create(name=name, actions=actions)
        return record.id


async def make_schedule(
    core: CoreEnv,
    *,
    cron: str,
    scenario_id: int | None = None,
    actions: list[Any] | None = None,
    cursor_ts: int | None = None,
    name: str = "расписание",
) -> int:
    async with core.db.session() as session:
        record = await ScheduleRepo(session).create(
            name=name,
            cron=cron,
            scenario_id=scenario_id,
            actions=actions,
            enabled=True,
        )
        record.cursor_ts = cursor_ts
        return record.id


async def set_cursor(core: CoreEnv, schedule_id: int, cursor_ts: int | None) -> None:
    async with core.db.session() as session:
        record = await ScheduleRepo(session).get(schedule_id)
        assert record is not None
        record.cursor_ts = cursor_ts


async def journal_count(core: CoreEnv) -> int:
    async with core.db.session() as session:
        result = await session.execute(select(func.count(CommandRecord.id)))
        return result.scalar_one()


async def journal_records(core: CoreEnv) -> list[CommandRecord]:
    async with core.db.session() as session:
        result = await session.execute(select(CommandRecord).order_by(CommandRecord.id))
        return list(result.scalars())


# --- validate_cron ----------------------------------------------------------


def test_validate_cron() -> None:
    assert validate_cron("0 23 * * *")
    assert validate_cron("*/5 8-22 * * 1,3,5")
    assert not validate_cron("60 23 * * *")  # минуты 60 нет
    assert not validate_cron("0 23 * *")  # 4 поля
    assert not validate_cron("0 23 * * * *")  # 6 полей
    assert not validate_cron("мусор")


# --- сценарии ----------------------------------------------------------------


async def test_scenario_merges_group_and_device_actions(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Группа + точечное действие: одна команда на устройство, поля мержатся."""
    first, second = await add_devices(core, 2)
    async with core.db.session() as session:
        group = await GroupRepo(session).create("Все")
        await GroupRepo(session).set_members(group.id, [first.uuid, second.uuid])
    scenario_id = await make_scenario(
        core,
        "Ночной режим",
        [
            {
                "target_type": "group",
                "target_id": group.id,
                "delta": {"fan_speed": 2, "sound": False},
            },
            {
                "target_type": "device",
                "target_id": first.uuid,
                "delta": {"fan_speed": 1},
            },
        ],
    )
    submissions = await automation.scenarios.run(
        scenario_id, source=CommandSource.SCENARIO, idempotency_prefix="run:1"
    )
    assert len(submissions) == 2  # по одной команде на устройство
    outcomes = {
        submission.device_uuid: await asyncio.wait_for(
            asyncio.shield(submission.ticket.outcome), 5
        )
        for submission in submissions
        if submission.ticket is not None
    }
    assert outcomes[first.uuid].result_state is not None
    assert outcomes[first.uuid].result_state["fan_speed"] == 1  # позднее победило
    assert outcomes[first.uuid].result_state["sound"] is False
    assert outcomes[second.uuid].result_state is not None
    assert outcomes[second.uuid].result_state["fan_speed"] == 2


async def test_scenario_not_found(automation: AutomationEnv) -> None:
    with pytest.raises(ScenarioNotFoundError):
        await automation.scenarios.run(
            999, source=CommandSource.SCENARIO, idempotency_prefix="run:x"
        )


async def test_scenario_unknown_device_rejected(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Цель вне реестра не валит сценарий — отказ по конкретному устройству."""
    scenario_id = await make_scenario(
        core,
        "Битый",
        [
            {
                "target_type": "device",
                "target_id": "нет-такого",
                "delta": {"power": True},
            }
        ],
    )
    submissions = await automation.scenarios.run(
        scenario_id, source=CommandSource.SCENARIO, idempotency_prefix="run:2"
    )
    assert len(submissions) == 1
    assert submissions[0].ticket is None
    assert submissions[0].rejected is not None


async def test_manual_scenario_run_places_hold(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Запуск кнопкой — ручное управление: приоритет 0 ставит manual-hold."""
    (device,) = await add_devices(core, 1)
    scenario_id = await make_scenario(
        core,
        "Проветривание",
        [
            {
                "target_type": "device",
                "target_id": device.uuid,
                "delta": {"fan_speed": 6},
            }
        ],
    )
    submissions = await automation.scenarios.run(
        scenario_id,
        source=CommandSource.SCENARIO,
        idempotency_prefix="run:3",
        priority=0,
    )
    assert submissions[0].ticket is not None
    await asyncio.wait_for(asyncio.shield(submissions[0].ticket.outcome), 5)
    assert core.holds.is_held(device.uuid)


# --- планировщик: базовый сценарий «23:00 → все на скорость 1» ---------------


async def night_mode_fixture(core: CoreEnv) -> tuple[list[Device], int, int]:
    """Три бризера в группе + сценарий «на скорость 1» + расписание 23:00."""
    devices = await add_devices(core, 3)
    async with core.db.session() as session:
        group = await GroupRepo(session).create("Все бризеры")
        await GroupRepo(session).set_members(
            group.id, [device.uuid for device in devices]
        )
    scenario_id = await make_scenario(
        core,
        "Ночной режим",
        [
            {
                "target_type": "group",
                "target_id": group.id,
                "delta": {"fan_speed": 1},
            }
        ],
    )
    schedule_id = await make_schedule(
        core, cron="0 23 * * *", scenario_id=scenario_id, cursor_ts=int(START)
    )
    return devices, scenario_id, schedule_id


async def run_and_wait_finished(
    core: CoreEnv, automation: AutomationEnv, count: int
) -> tuple[int, list[dict[str, Any]]]:
    """Шаг планировщика с подпиской ДО запуска — события не теряются."""
    events: list[dict[str, Any]] = []
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as subscription:
        fired = await automation.scheduler.run_pending()
        while len(events) < count:
            event = await asyncio.wait_for(subscription.get(), 5)
            events.append(event.data)
    return fired, events


async def test_schedule_fires_night_mode_e2e(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Гейт фазы: «23:00 → все на скорость 1» на фейках, от cron до железа."""
    devices, _, _ = await night_mode_fixture(core)
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as subscription:
        await automation.clock.advance(90)  # 22:59 → 23:00:30
        fired = await automation.scheduler.run_pending()
        assert fired == 1
        finished = [
            (await asyncio.wait_for(subscription.get(), 5)).data for _ in range(3)
        ]
    assert {event["device_uuid"] for event in finished} == {
        device.uuid for device in devices
    }
    assert all(event["status"] == "done" for event in finished)
    assert all(event["result_state"]["fan_speed"] == 1 for event in finished)
    records = await journal_records(core)
    assert all(record.source == "schedule" for record in records)
    assert all(record.priority == 2 for record in records)

    # повторный шаг тем же временем — курсор сдвинут, дублей нет
    assert await automation.scheduler.run_pending() == 0
    assert await journal_count(core) == 3


async def test_schedule_first_sight_does_not_catch_up(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Новое расписание (курсор NULL): прошлое не догоняется, курсор — «сейчас»."""
    (device,) = await add_devices(core, 1)
    await make_schedule(
        core,
        cron="0 22 * * *",  # сегодня в 22:00 уже прошло
        actions=[
            {
                "target_type": "device",
                "target_id": device.uuid,
                "delta": {"power": False},
            }
        ],
    )
    assert await automation.scheduler.run_pending() == 0
    assert await journal_count(core) == 0
    # а следующее срабатывание — завтра в 22:00 — уже исполняется
    automation.clock._now = msk(2026, 7, 13, 22, 1)
    assert await automation.scheduler.run_pending() == 1


async def test_schedule_restart_within_tolerance_fires(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Рестарт: опоздание < 5 минут — пропущенное срабатывание исполняется."""
    await night_mode_fixture(core)
    # сервис «лежал» с 22:59 до 23:02
    automation.clock._now = msk(2026, 7, 12, 23, 2)
    fired, _ = await run_and_wait_finished(core, automation, 3)
    assert fired == 1


async def test_schedule_restart_beyond_tolerance_skips(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Рестарт: опоздание > 5 минут — пропуск с логом, курсор сдвигается."""
    await night_mode_fixture(core)
    automation.clock._now = msk(2026, 7, 12, 23, 20)
    assert await automation.scheduler.run_pending() == 0
    assert await journal_count(core) == 0
    # курсор сдвинут на пропущенное срабатывание: до завтрашних 23:00 тихо
    automation.clock._now = msk(2026, 7, 13, 12, 0)
    assert await automation.scheduler.run_pending() == 0
    automation.clock._now = msk(2026, 7, 13, 23, 1)
    assert await automation.scheduler.run_pending() == 1


async def test_schedule_crash_replay_is_idempotent(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Падение между запуском и сдвигом курсора: повтор дедупится журналом."""
    _, _, schedule_id = await night_mode_fixture(core)
    await automation.clock.advance(90)
    fired, _ = await run_and_wait_finished(core, automation, 3)
    assert fired == 1
    assert await journal_count(core) == 3

    await set_cursor(core, schedule_id, int(START))  # «курсор не записался»
    assert await automation.scheduler.run_pending() == 1  # повторный «запуск»
    assert await journal_count(core) == 3  # но новых команд нет — дедуп по ключу


async def test_hold_blocks_schedule(core: CoreEnv, automation: AutomationEnv) -> None:
    """Manual-hold: расписание пропускается со статусом skipped_hold (FR-23)."""
    devices, _, _ = await night_mode_fixture(core)
    core.holds.place(devices[0].uuid)
    await automation.clock.advance(90)
    fired, finished = await run_and_wait_finished(core, automation, 3)
    assert fired == 1
    by_device = {event["device_uuid"]: event["status"] for event in finished}
    assert by_device[devices[0].uuid] == "skipped_hold"
    others = [devices[1].uuid, devices[2].uuid]
    assert all(by_device[uuid] == "done" for uuid in others)


async def test_scheduler_loop_wakes_by_clock_and_event(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Вечный цикл: сон до cron-момента по Clock, пробуждение по CRUD-событию."""
    (device,) = await add_devices(core, 1)
    await automation.scheduler.start()
    try:
        # цикл заснул на дежурный час (расписаний нет); CRUD будит его
        await make_schedule(
            core,
            cron="* * * * *",
            actions=[
                {
                    "target_type": "device",
                    "target_id": device.uuid,
                    "delta": {"fan_speed": 3},
                }
            ],
            cursor_ts=int(automation.clock.now()),
        )
        core.events.publish(TOPIC_AUTOMATION_CHANGED, {"kind": "schedule"})
        with core.events.subscribe(TOPIC_COMMAND_FINISHED) as subscription:
            await automation.clock.advance(61)  # следующая минута наступила
            event = await asyncio.wait_for(subscription.get(), 5)
        assert event.data["status"] == "done"
        assert event.data["result_state"]["fan_speed"] == 3
    finally:
        await automation.scheduler.stop()


# --- DST (Europe/Berlin, фактическое поведение croniter) ---------------------


def berlin(*args: int) -> float:
    return datetime(*args, tzinfo=BERLIN).timestamp()  # type: ignore[arg-type]


async def test_dst_spring_forward_fires_once_shifted(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Весна: несуществующее 02:30 сдвигается к 03:00, ровно один запуск."""
    scheduler = SchedulerService(
        core.db, automation.scenarios, core.events, automation.clock, tz=BERLIN
    )
    due = scheduler._due_occurrences(
        "30 2 * * *", berlin(2026, 3, 28, 12, 0), berlin(2026, 3, 29, 12, 0)
    )
    assert len(due) == 1
    fired_at = datetime.fromtimestamp(due[0], tz=BERLIN)
    assert (fired_at.hour, fired_at.minute) == (3, 0)


async def test_dst_fall_back_fires_in_both_offsets(
    core: CoreEnv, automation: AutomationEnv
) -> None:
    """Осень: неоднозначное 02:30 срабатывает в обоих смещениях (+02 и +01).

    Для идемпотентных сценариев двойной запуск безвреден; фиксируем поведение.
    """
    scheduler = SchedulerService(
        core.db, automation.scenarios, core.events, automation.clock, tz=BERLIN
    )
    due = scheduler._due_occurrences(
        "30 2 * * *", berlin(2026, 10, 24, 12, 0), berlin(2026, 10, 25, 12, 0)
    )
    assert len(due) == 2
    assert due[0] < due[1]
    assert due[1] - due[0] == 3600  # тот же настенный момент через час
