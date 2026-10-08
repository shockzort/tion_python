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

    # SET, затем контрольный REQUEST_PARAMS (кадр после SET может потеряться,
    # а прошивка вправе скорректировать поля — спека §1.6)
    assert [frame.opcode for frame in device.received_frames[-2:]] == [
        OPCODE_SET_PARAMS,
        OPCODE_REQUEST_PARAMS,
    ]
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


async def test_expired_response_cannot_complete_new_request_or_refresh_cache() -> None:
    device = FakeS4Device()
    device.drop_responses = 2
    transport = FakeTransport(device)
    driver = S4Driver(transport, response_timeout=0.1)
    received: list[S4State] = []
    driver.on_state = received.append
    async with driver:
        with pytest.raises(DriverTimeoutError):
            await driver.get_state()
        old_id = device.received_frames[0].request_id
        pending = asyncio.create_task(driver.get_state())
        await _wait_frames(device, 2)
        new_id = device.received_frames[1].request_id
        assert old_id != new_id
        for packet in device.state_packets(old_id):
            driver._handle_packet(packet)
        assert driver.last_state is None
        assert not received and not pending.done()

        # Push остаётся полезным, но не подтверждает активный GET.
        for packet in device.state_packets():
            driver._handle_packet(packet)
        assert driver.last_state == DEFAULT_STATE
        assert not pending.done()
        device.state = dataclasses.replace(DEFAULT_STATE, fan_speed=5)
        for packet in device.state_packets(new_id):
            driver._handle_packet(packet)
        assert (await pending).fan_speed == 5
        for packet in FakeS4Device().state_packets(old_id):
            driver._handle_packet(packet)
        assert driver.last_state.fan_speed == 5


async def _wait_frames(device: FakeS4Device, count: int) -> None:
    async with asyncio.timeout(1):
        while len(device.received_frames) < count:
            await asyncio.sleep(0)


async def test_late_set_ack_cannot_replace_readback() -> None:
    class SilentReadback(FakeS4Device):
        def handle_packet(self, packet: bytes) -> list[bytes]:
            super().handle_packet(packet)
            return []

    device = SilentReadback()
    driver = S4Driver(FakeTransport(device), response_timeout=0.1)
    async with driver:
        pending = asyncio.create_task(
            driver.set_state(dataclasses.replace(DEFAULT_STATE, fan_speed=6))
        )
        await _wait_frames(device, 2)
        set_id, get_id = (f.request_id for f in device.received_frames)
        for packet in FakeS4Device().state_packets(set_id):
            driver._handle_packet(packet)
        assert driver.last_state is None and not pending.done()
        for packet in device.state_packets(get_id):
            driver._handle_packet(packet)
        assert (await pending).fan_speed == 6


async def test_write_failure_cleans_waiter_and_readback_checks_applied_set() -> None:
    from easy_breezy.ble.driver import DriverError
    from easy_breezy.ble.transport import TransportError

    class AmbiguousWrite(FakeTransport):
        async def write(self, packet: bytes) -> None:
            before = len(self.device.received_frames)
            await super().write(packet)
            if len(self.device.received_frames) > before and (
                self.device.received_frames[-1].opcode == OPCODE_SET_PARAMS
            ):
                raise TransportError("запись выполнена, подтверждение потеряно")

    device = FakeS4Device()
    driver = S4Driver(AmbiguousWrite(device))
    async with driver:
        result = await driver.set_state(dataclasses.replace(DEFAULT_STATE, fan_speed=4))
        assert result.fan_speed == 4
        assert [f.opcode for f in device.received_frames] == [
            OPCODE_SET_PARAMS,
            OPCODE_REQUEST_PARAMS,
        ]
        assert driver._state_waiter is None

    failed, transport, _ = make_driver()
    transport.fail_writes = True
    async with failed:
        with pytest.raises(DriverError):
            await failed.set_state(DEFAULT_STATE)
        assert failed._state_waiter is None and failed._request_id is None


async def test_cancelled_set_cleans_waiter_and_releases_lock() -> None:
    driver, transport, _ = make_driver()
    transport.write_delay = 1
    async with driver:
        pending = asyncio.create_task(driver.set_state(DEFAULT_STATE))
        await asyncio.sleep(0)
        waiter = driver._state_waiter
        assert waiter is not None
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert waiter.cancelled() and driver._state_waiter is None
        transport.write_delay = 0
        assert await driver.get_state() == DEFAULT_STATE


async def test_default_budget_covers_silent_set_and_slow_readback() -> None:
    class SlowReadback(FakeTransport):
        async def write(self, packet: bytes) -> None:
            # SET из двух пакетов проходит сразу; контрольный GET — через 1.18 с.
            if self.device.received_frames:
                await asyncio.sleep(1.18)
            await super().write(packet)

    device = FakeS4Device()
    device.push_state_after_set = False
    driver = S4Driver(SlowReadback(device))  # реальные 3 секунды ожидания ACK
    async with driver:
        driver.last_state = DEFAULT_STATE
        actual = await driver.update_state(
            lambda base: dataclasses.replace(base, fan_speed=4)
        )
        assert actual.fan_speed == 4
        assert sum(f.opcode == OPCODE_SET_PARAMS for f in device.received_frames) == 1


async def test_waiting_for_poll_does_not_consume_execution_budget() -> None:
    driver, transport, _ = make_driver()
    transport.write_delay = 0.06
    async with driver:
        poll = asyncio.create_task(driver.get_state())
        await asyncio.sleep(0)
        command = asyncio.create_task(
            driver.update_state(
                lambda base: dataclasses.replace(base, fan_speed=4),
                execute_timeout=0.21,
            )
        )
        await poll
        assert (await command).fan_speed == 4  # ~0.24 с вместе, SET+GET ~0.18 с
