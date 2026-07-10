"""Драйвер S4 на фейковом транспорте: запрос/ответ, подтверждения, сбои."""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from easy_breezy.ble.driver import DriverTimeoutError, S4Driver
from easy_breezy.ble.fake import DEFAULT_STATE, FakeS4Device, FakeTransport
from easy_breezy.ble.protocol.s4 import (
    OPCODE_REQUEST_PARAMS,
    OPCODE_SET_PARAMS,
    Mode,
    S4State,
)


def _fixed_rng(n: int) -> bytes:
    return bytes(range(1, n + 1))


def make_driver(
    device: FakeS4Device | None = None, *, response_timeout: float = 0.2
) -> tuple[S4Driver, FakeTransport, FakeS4Device]:
    dev = device or FakeS4Device()
    transport = FakeTransport(dev)
    driver = S4Driver(transport, response_timeout=response_timeout, rng=_fixed_rng)
    return driver, transport, dev


async def test_get_state_returns_device_state() -> None:
    driver, _, device = make_driver()
    async with driver:
        state = await driver.get_state()
    assert state == device.state == DEFAULT_STATE
    assert driver.last_state == state


async def test_set_state_applies_and_confirms() -> None:
    driver, _, device = make_driver()
    desired = S4State(
        power=True,
        sound=False,
        light=True,
        heater=True,
        mode=Mode.RECIRCULATION,
        heater_temp=22,
        fan_speed=5,
        in_temp=0,
        out_temp=0,
        filter_remain_seconds=0,
    )
    async with driver:
        confirmed = await driver.set_state(desired)

    assert device.received_frames[-1].opcode == OPCODE_SET_PARAMS
    # управляемые поля подтверждены устройством
    for field in (
        "power",
        "sound",
        "light",
        "heater",
        "mode",
        "heater_temp",
        "fan_speed",
    ):
        assert getattr(confirmed, field) == getattr(desired, field), field
    # телеметрия — от устройства, не из запроса
    assert confirmed.in_temp == DEFAULT_STATE.in_temp


async def test_set_state_falls_back_to_explicit_request() -> None:
    device = FakeS4Device()
    device.push_state_after_set = False  # устройство молчит после SET
    driver, _, _ = make_driver(device)

    desired = dataclasses.replace(DEFAULT_STATE, fan_speed=6)
    async with driver:
        confirmed = await driver.set_state(desired)

    assert confirmed.fan_speed == 6
    opcodes = [frame.opcode for frame in device.received_frames]
    assert opcodes == [OPCODE_SET_PARAMS, OPCODE_REQUEST_PARAMS]


async def test_get_state_timeout_raises() -> None:
    device = FakeS4Device()
    device.drop_responses = 2  # запрос и fallback уйдут в тишину
    driver, _, _ = make_driver(device)

    async with driver:
        with pytest.raises(DriverTimeoutError, match="нет кадра состояния"):
            await driver.get_state()


async def test_corrupted_crc_is_soft() -> None:
    """Мягкий режим CRC: битый трейлер не мешает разбору (спека §1.3)."""
    device = FakeS4Device()
    device.corrupt_crc = True
    driver, _, _ = make_driver(device)

    async with driver:
        state = await driver.get_state()
    assert state == device.state


async def test_unsolicited_push_updates_state_and_callback() -> None:
    driver, transport, device = make_driver()
    received: list[S4State] = []
    driver.on_state = received.append

    async with driver:
        transport.push_state()
        async with asyncio.timeout(1):
            while not received:
                await asyncio.sleep(0)

    assert received == [device.state]
    assert driver.last_state == device.state


async def test_disconnect_mid_request_fails_fast() -> None:
    device = FakeS4Device()
    device.drop_responses = 1  # запрос уйдёт в тишину
    driver, transport, _ = make_driver(device, response_timeout=5.0)
    async with driver:
        task = asyncio.ensure_future(driver.get_state())
        await asyncio.sleep(0)  # запрос ушёл, ответа не будет

        transport.simulate_connection_loss()
        with pytest.raises(Exception, match=r"разорвано|нет кадра"):
            async with asyncio.timeout(1):
                await task


async def test_serialized_operations() -> None:
    """Параллельные вызовы сериализуются per-device локом."""
    driver, _, device = make_driver()
    async with driver:
        results = await asyncio.gather(
            driver.get_state(), driver.get_state(), driver.get_state()
        )
    assert all(state == device.state for state in results)
    assert len(device.received_frames) == 3
