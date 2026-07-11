"""Командная шина: дедуп, сериализация, приоритеты, hold, отказы (план §8)."""

from __future__ import annotations

import asyncio

import pytest

from easy_breezy.ble.protocol.s4 import OPCODE_SET_PARAMS
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.bus import CommandError, CommandOutcome, CommandTicket
from easy_breezy.core.events import TOPIC_COMMAND_FINISHED
from easy_breezy.core.model import StateDelta
from easy_breezy.storage.models import CommandSource, CommandStatus, Device
from easy_breezy.storage.repos import CommandRepo
from tests.conftest import CoreEnv, wait_for_condition

MAC = "FA:KE:00:00:00:01"


async def outcome_of(ticket: CommandTicket, timeout: float = 5.0) -> CommandOutcome:
    """Ждёт итог, не отменяя общий Future (он разделяется дедупом)."""
    return await asyncio.wait_for(asyncio.shield(ticket.outcome), timeout)


def set_fan_frames(core: CoreEnv, mac: str = MAC) -> list[int]:
    """Скорости из принятых устройством SET-кадров — фактический порядок записей."""
    return [
        frame.payload[4]
        for frame in core.fleet.device(mac).received_frames
        if frame.opcode == OPCODE_SET_PARAMS
    ]


@pytest.fixture
async def device(core: CoreEnv) -> Device:
    added = await core.registry.add_device(mac=MAC, name="Тест")
    await wait_for_condition(
        lambda: core.registry.connection(added.uuid) is ConnectionState.ONLINE
    )
    return added


async def test_command_done_with_actual_state_and_event(
    core: CoreEnv, device: Device
) -> None:
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as sub:
        ticket = await core.bus.submit(
            device_uuid=device.uuid,
            delta=StateDelta(fan_speed=4),
            source=CommandSource.UI,
            idempotency_key="ui:1",
        )
        outcome = await outcome_of(ticket)
        assert outcome.status is CommandStatus.DONE
        assert outcome.result_state is not None
        assert outcome.result_state["fan_speed"] == 4

        event = await asyncio.wait_for(sub.get(), 1)
        assert event.data["command_id"] == ticket.command_id
        assert event.data["status"] == "done"

    assert core.fleet.device(MAC).state.fan_speed == 4
    async with core.db.session() as session:
        record = await CommandRepo(session).get(ticket.command_id)
        assert record is not None
        assert record.status == CommandStatus.DONE
        assert record.result_state is not None
        assert record.payload == {"fan_speed": 4}


async def test_dedup_inflight_single_execution(core: CoreEnv, device: Device) -> None:
    core.fleet.transport(MAC).write_delay = 0.05  # даём окно «в полёте»
    first = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=5),
        source=CommandSource.YANDEX,
        idempotency_key="yandex:req-1:dev",
    )
    second = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=5),
        source=CommandSource.YANDEX,
        idempotency_key="yandex:req-1:dev",
    )
    assert second is first  # общая квитанция, общий Future
    outcome = await outcome_of(first)
    assert outcome.status is CommandStatus.DONE
    assert set_fan_frames(core) == [5]  # исполнение ровно одно


async def test_dedup_from_journal_returns_saved_result(
    core: CoreEnv, device: Device
) -> None:
    ticket = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=3),
        source=CommandSource.UI,
        idempotency_key="ui:replay",
    )
    saved = await outcome_of(ticket)

    replay = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=3),
        source=CommandSource.UI,
        idempotency_key="ui:replay",
    )
    outcome = await outcome_of(replay)
    assert replay.command_id == ticket.command_id
    assert outcome.status is CommandStatus.DONE
    assert outcome.result_state == saved.result_state
    assert set_fan_frames(core) == [3]  # повторного исполнения не было


async def test_priority_overtakes_queue_order(core: CoreEnv, device: Device) -> None:
    core.fleet.transport(MAC).write_delay = 0.05  # первый занимает воркера
    slow = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=2),
        source=CommandSource.SCHEDULE,
        idempotency_key="s:1",
    )
    queued = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=3),
        source=CommandSource.SCHEDULE,
        idempotency_key="s:2",
    )
    urgent = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=6),
        source=CommandSource.TRIGGER,  # приоритет 1 — обгоняет расписание
        idempotency_key="t:1",
    )
    for ticket in (slow, queued, urgent):
        assert (await outcome_of(ticket)).status is CommandStatus.DONE
    assert set_fan_frames(core) == [2, 6, 3]


async def test_manual_hold_skips_automation(core: CoreEnv, device: Device) -> None:
    manual = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=4),
        source=CommandSource.UI,
        idempotency_key="ui:manual",
    )
    assert (await outcome_of(manual)).status is CommandStatus.DONE
    assert core.holds.is_held(device.uuid)

    automation = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=1),
        source=CommandSource.SCHEDULE,
        idempotency_key="s:blocked",
    )
    outcome = await outcome_of(automation)
    assert outcome.status is CommandStatus.SKIPPED_HOLD
    assert core.fleet.device(MAC).state.fan_speed == 4  # автоматика не прошла

    core.holds.release(device.uuid)
    retried = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=1),
        source=CommandSource.SCHEDULE,
        idempotency_key="s:after-release",
    )
    assert (await outcome_of(retried)).status is CommandStatus.DONE
    assert core.fleet.device(MAC).state.fan_speed == 1


async def test_antiflood_supersedes_oldest_schedule(
    core: CoreEnv, device: Device
) -> None:
    core.fleet.transport(MAC).write_delay = 0.1  # воркер занят первым
    running = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=2),
        source=CommandSource.SCHEDULE,
        idempotency_key="s:running",
    )
    queued = [
        await core.bus.submit(
            device_uuid=device.uuid,
            delta=StateDelta(fan_speed=3),
            source=CommandSource.SCHEDULE,
            idempotency_key=f"s:q{i}",
        )
        for i in range(4)  # глубина 4 > max_queue_depth=2 из фикстуры
    ]
    statuses = [(await outcome_of(t)).status for t in (running, *queued)]
    assert statuses[0] is CommandStatus.DONE
    assert statuses[1:3] == [CommandStatus.SUPERSEDED, CommandStatus.SUPERSEDED]
    assert statuses[3:] == [CommandStatus.DONE, CommandStatus.DONE]

    async with core.db.session() as session:
        record = await CommandRepo(session).get(queued[0].command_id)
        assert record is not None
        assert record.status == CommandStatus.SUPERSEDED


async def test_unreachable_device_fails_fast(core: CoreEnv) -> None:
    mac = "FA:KE:00:00:00:99"
    core.fleet.connect_failures[mac] = 1  # каждый транспорт падает на connect
    silent = await core.registry.add_device(mac=mac, name="Недоступный")
    ticket = await core.bus.submit(
        device_uuid=silent.uuid,
        delta=StateDelta(power=False),
        source=CommandSource.UI,
        idempotency_key="ui:dead",
    )
    outcome = await outcome_of(ticket)
    assert outcome.status is CommandStatus.FAILED
    assert outcome.error == "устройство недоступно"


async def test_transient_failure_retried_once(core: CoreEnv, device: Device) -> None:
    fake = core.fleet.device(MAC)
    fake.drop_responses = 2  # SET и контрольный REQUEST первой попытки — в тишину
    ticket = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=6),
        source=CommandSource.UI,
        idempotency_key="ui:flaky",
    )
    outcome = await outcome_of(ticket)
    assert outcome.status is CommandStatus.DONE
    assert set_fan_frames(core) == [6, 6]  # вторая попытка добила
    assert fake.state.fan_speed == 6


async def test_persistent_silence_times_out(core: CoreEnv, device: Device) -> None:
    core.fleet.device(MAC).drop_responses = 10_000
    ticket = await core.bus.submit(
        device_uuid=device.uuid,
        delta=StateDelta(fan_speed=5),
        source=CommandSource.UI,
        idempotency_key="ui:silence",
    )
    outcome = await outcome_of(ticket)
    assert outcome.status is CommandStatus.TIMEOUT
    assert outcome.error is not None


async def test_submit_validation(core: CoreEnv, device: Device) -> None:
    with pytest.raises(CommandError, match="пустая дельта"):
        await core.bus.submit(
            device_uuid=device.uuid,
            delta=StateDelta(),
            source=CommandSource.UI,
            idempotency_key="ui:empty",
        )
    with pytest.raises(CommandError, match="не в реестре"):
        await core.bus.submit(
            device_uuid="неизвестный",
            delta=StateDelta(fan_speed=1),
            source=CommandSource.UI,
            idempotency_key="ui:ghost",
        )
