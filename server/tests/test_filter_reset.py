"""Сброс ресурса S4: одно действие, контрольное чтение и ошибки без ретрая."""

from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest

from easy_breezy.ble.driver import FilterResetUnconfirmed
from easy_breezy.ble.fake import DEFAULT_STATE
from easy_breezy.ble.protocol.framing import parse_frame
from easy_breezy.ble.protocol.s4 import (
    OPCODE_REQUEST_PARAMS,
    OPCODE_SET_PARAMS,
    decode_state,
    encode_set_params,
    encode_state_payload,
)
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.bus import CommandError
from easy_breezy.storage.repos import CommandRepo
from tests.conftest import (
    ClientAndApp,
    CoreEnv,
    bootstrap_admin,
    container_of,
    wait_devices_online,
    wait_for_condition,
)
from tests.test_driver import make_driver


def test_full_counter_and_reset_payload() -> None:
    state = replace(DEFAULT_STATE, filter_remain_seconds=365 * 86400)
    assert decode_state(encode_state_payload(state)).filter_remain_seconds == 31536000
    frame = parse_frame(
        encode_set_params(
            state,
            rand=1,
            request_id=bytes(4),
            extra=bytes(4),
            filter_reset=True,
        )
    )
    assert frame.payload[0] & 0x80
    assert frame.payload[5:7] == bytes(2)
    assert frame.payload[2:5] == bytes([0, state.heater_temp, state.fan_speed])


async def test_reset_reads_actual_base_and_is_repeatable_when_already_reset() -> None:
    driver, _, device = make_driver()
    device.filter_reset_seconds = 365 * 86400
    device.state = replace(
        DEFAULT_STATE, fan_speed=5, heater=True, filter_remain_seconds=100
    )
    expected = replace(device.state, filter_remain_seconds=365 * 86400)
    async with driver:
        driver.last_state = DEFAULT_STATE  # устаревший кэш нельзя записать назад
        assert await driver.reset_filter(expected_days=365) == expected
        assert await driver.reset_filter(expected_days=365) == expected
    assert [f.opcode for f in device.received_frames] == [
        OPCODE_REQUEST_PARAMS,
        OPCODE_SET_PARAMS,
        OPCODE_REQUEST_PARAMS,
    ] * 2


async def test_ignored_reset_not_successful_and_no_repeat_write() -> None:
    driver, _, device = make_driver()
    device.state = replace(DEFAULT_STATE, filter_remain_seconds=10 * 86400)
    device.ignore_filter_reset = True
    async with driver:
        with pytest.raises(FilterResetUnconfirmed) as error:
            await driver.reset_filter(expected_days=180)
    assert error.value.actual == device.state
    assert sum(f.opcode == OPCODE_SET_PARAMS for f in device.received_frames) == 1


async def test_silent_set_is_checked_by_reread() -> None:
    driver, _, device = make_driver(response_timeout=0.01)
    device.push_state_after_set = False
    async with driver:
        state = await driver.reset_filter(expected_days=180)
    assert state.filter_remain_days == 180


async def test_read_failure_after_write_never_resends() -> None:
    driver, transport, device = make_driver(response_timeout=0.01)
    original = device._apply_set

    def apply_and_lose_link(payload: bytes) -> None:
        original(payload)
        transport.fail_writes = True

    device._apply_set = apply_and_lose_link
    async with driver:
        with pytest.raises(FilterResetUnconfirmed):
            await driver.reset_filter(expected_days=180)
    assert sum(f.opcode == OPCODE_SET_PARAMS for f in device.received_frames) == 1


async def test_bus_dedup_concurrent_reset_no_hold_and_offline_rejection(
    core: CoreEnv,
) -> None:
    device = await core.registry.add_device(mac="FA:KE:00:00:00:01", name="Тест")
    await wait_for_condition(
        lambda: core.registry.connection(device.uuid) is ConnectionState.ONLINE
    )
    with pytest.raises(CommandError, match="не проверен"):
        await core.bus.submit_filter_reset(
            device_uuid=device.uuid, idempotency_key="blocked"
        )
    core.bus._filter_reset_days[device.uuid] = 180
    core.fleet.transport(device.mac).write_delay = 0.02
    first = await core.bus.submit_filter_reset(
        device_uuid=device.uuid, idempotency_key="same"
    )
    again = await core.bus.submit_filter_reset(
        device_uuid=device.uuid, idempotency_key="same"
    )
    assert again is first
    with pytest.raises(CommandError, match="уже выполняется"):
        await core.bus.submit_filter_reset(
            device_uuid=device.uuid, idempotency_key="other-tab"
        )
    result = await asyncio.wait_for(first.outcome, 2)
    assert result.status == "done"
    assert not core.holds.is_held(device.uuid)
    restored = await core.bus.submit_filter_reset(
        device_uuid=device.uuid, idempotency_key="same"
    )
    assert (await restored.outcome) == result
    async with core.db.session() as session:
        record = await CommandRepo(session).get(first.command_id)
        assert record is not None and record.payload == {"operation": "filter_reset"}
    await core.registry.stop()
    with pytest.raises(CommandError):
        await core.bus.submit_filter_reset(
            device_uuid=device.uuid, idempotency_key="offline"
        )


def test_api_pending_poll_idempotence_and_auth(client_app: ClientAndApp) -> None:
    client, app = client_app
    assert client.post("/api/devices/no/filter-reset").status_code == 401
    bootstrap_admin(client, app)
    device = wait_devices_online(client)[0]
    assert device["filter_reset_supported"]
    container_of(app).settings.command_wait_seconds = 0.00001
    url = f"/api/devices/{device['uuid']}/filter-reset"
    assert client.post(url).status_code == 422
    result = client.post(url, headers={"Idempotency-Key": "reset-test"})
    assert result.status_code == 202
    cid = result.json()["command_id"]
    for _ in range(100):
        record = client.get(f"/api/commands/{cid}").json()
        if record["status"] not in ("pending", "running"):
            break
        import time

        time.sleep(0.01)
    assert record["status"] == "done"
    assert (
        client.post(url, headers={"Idempotency-Key": "reset-test"}).json()["command_id"]
        == cid
    )
    assert client.get(f"/api/devices/{device['uuid']}").json()["hold_until"] is None
