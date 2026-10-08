"""Ошибки BlueZ: частичный connect, зависшие scan/DBus, отмена и cleanup."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from dbus_fast import Message, MessageType, Variant

from easy_breezy.ble import discovery, scanner, transport
from easy_breezy.ble.protocol.s4 import GATT_NOTIFY, GATT_WRITE
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.ble.transport import BleakTransport, TransportError
from easy_breezy.core import watchdog
from tests.conftest import FakeClock


def make_transport() -> BleakTransport:
    return BleakTransport(
        "AA:BB:CC:DD:EE:FF",
        notify_uuid=GATT_NOTIFY,
        write_uuid=GATT_WRITE,
        operation_timeout=0.01,
    )


def ble_device() -> BLEDevice:
    return BLEDevice(
        "AA:BB:CC:DD:EE:FF",
        "Breezer 4S",
        {"path": "/org/bluez/hci0/dev_AA_BB_CC_DD_EE_FF"},
    )


@pytest.mark.parametrize("failure", ["error", "timeout", "cancel"])
async def test_notify_failure_closes_partial_connection(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    notifying = asyncio.Event()
    client = MagicMock(is_connected=False)

    async def connect() -> None:
        client.is_connected = True

    async def notify(*_args: object) -> None:
        notifying.set()
        if failure == "error":
            raise BleakError("org.bluez.Error.Failed")
        await asyncio.Event().wait()

    async def disconnect() -> None:
        client.is_connected = False

    client.connect = AsyncMock(side_effect=connect)
    client.start_notify = AsyncMock(side_effect=notify)
    client.disconnect = AsyncMock(side_effect=disconnect)
    monkeypatch.setattr(transport, "BleakClient", MagicMock(return_value=client))
    target = make_transport()
    pending = asyncio.create_task(target._attach(ble_device()))
    await asyncio.wait_for(notifying.wait(), 1)
    if failure == "cancel":
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    else:
        with pytest.raises(TransportError, match="start_notify"):
            await asyncio.wait_for(pending, 1)
    assert not target.is_connected and not client.is_connected
    await target.disconnect()
    client.disconnect.assert_awaited_once()


@pytest.mark.parametrize("stage", ["start", "stop"])
async def test_scan_deadline_releases_gate(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    async def hang() -> None:
        await asyncio.Event().wait()

    active = MagicMock(discovered_devices_and_advertisement_data={})
    active.start = AsyncMock(side_effect=hang if stage == "start" else None)
    active.stop = AsyncMock(side_effect=hang if stage == "stop" else None)
    monkeypatch.setattr(scanner, "BleakScanner", MagicMock(return_value=active))
    monkeypatch.setattr(discovery, "SCAN_OPERATION_TIMEOUT", 0.01)
    gate = asyncio.Lock()
    with pytest.raises(TransportError):
        await asyncio.wait_for(scanner.scan(0, gate=gate), 1)
    active.stop.assert_awaited_once()
    assert not gate.locked()


@pytest.mark.parametrize("stage", ["connect", "Get", "RegisterAgent", "Pair"])
async def test_pair_dbus_failure_cleans_bus_and_adapter(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    bus = MagicMock()
    blocked = asyncio.Event()
    calls: list[Message] = []

    async def connect() -> None:
        if stage == "connect":
            blocked.set()
            await asyncio.Event().wait()

    async def call(message: Message) -> Message:
        calls.append(message)
        if message.member == stage:
            blocked.set()
            await asyncio.Event().wait()
        if message.member == "Get":
            return Message(
                message_type=MessageType.METHOD_RETURN,
                reply_serial=1,
                signature="v",
                body=[Variant("b", False)],
            )
        return Message(message_type=MessageType.METHOD_RETURN, reply_serial=1)

    bus.connect = AsyncMock(side_effect=connect)
    bus.call = AsyncMock(side_effect=call)
    monkeypatch.setattr(transport, "MessageBus", MagicMock(return_value=bus))
    monkeypatch.setattr(
        BleakTransport, "_find_device", AsyncMock(return_value=ble_device())
    )
    target = make_transport()
    pending = asyncio.create_task(target.pair())
    await asyncio.wait_for(blocked.wait(), 1)
    if stage == "Pair":
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert [m.member for m in calls][-4:] == [
            "CancelPairing",
            "Disconnect",
            "UnregisterAgent",
            "Set",
        ]
    else:
        with pytest.raises(TransportError):
            await asyncio.wait_for(pending, 1)
    bus.disconnect.assert_called_once()
    if stage in ("RegisterAgent", "Pair"):
        assert calls[-1].member == "Set" and calls[-1].body[-1].value is False
        bus.unexport.assert_called_once()


async def test_watchdog_hung_reset_does_not_block_next_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def hang() -> bool:
        await asyncio.Event().wait()
        return True

    monkeypatch.setattr(watchdog, "ADAPTER_RESET_TIMEOUT_SECONDS", 0.01)
    clock = FakeClock(0)
    terminate = MagicMock()
    target = watchdog.BleWatchdog(
        lambda: {"a": ConnectionState.DISCONNECTED},
        clock,
        adapter_reset=hang,
        terminate=terminate,
    )
    await target.check_once()
    await clock.advance(601)
    await asyncio.wait_for(target.check_once(), 1)
    terminate.assert_not_called()
    await clock.advance(601)
    await target.check_once()
    terminate.assert_called_once()


async def test_cancelled_adapter_reset_attempts_to_restore_power(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import dbus_fast.aio

    bus = MagicMock()
    bus.connect = AsyncMock()
    bus.introspect = AsyncMock()
    manager = MagicMock()
    manager.call_get_managed_objects = AsyncMock(
        return_value={"/org/bluez/hci0": {"org.bluez.Adapter1": {}}}
    )
    props = MagicMock()
    off_started = asyncio.Event()
    powered: list[bool] = []

    async def set_power(_iface: str, _prop: str, value: Variant) -> None:
        powered.append(value.value)
        if not value.value:
            off_started.set()
            await asyncio.Event().wait()

    props.call_set = AsyncMock(side_effect=set_power)
    proxy = MagicMock()
    proxy.get_interface.side_effect = [manager, props]
    bus.get_proxy_object.return_value = proxy
    monkeypatch.setattr(dbus_fast.aio, "MessageBus", MagicMock(return_value=bus))
    task = asyncio.create_task(watchdog.reset_bluetooth_adapters())
    await asyncio.wait_for(off_started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert powered == [False, True]
    bus.disconnect.assert_called_once()


async def test_internal_connect_retry_does_not_end_successful_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from easy_breezy.ble.driver import S4Driver
    from easy_breezy.ble.fake import FakeS4Device

    device = FakeS4Device()
    target = make_transport()
    client = MagicMock(is_connected=False)

    async def connect() -> None:
        # Bleak повторяет connect внутри одного вызова, уведомляя о разрывах.
        target._on_disconnect(client)
        target._on_disconnect(client)
        client.is_connected = True

    async def write(_uuid: str, packet: bytes, *, response: bool) -> None:
        for payload in device.handle_packet(packet):
            target._on_notify(None, bytearray(payload))

    client.connect = AsyncMock(side_effect=connect)
    client.start_notify = AsyncMock()
    client.disconnect = AsyncMock()
    client.write_gatt_char = AsyncMock(side_effect=write)
    monkeypatch.setattr(transport, "BleakClient", MagicMock(return_value=client))
    monkeypatch.setattr(
        BleakTransport, "_find_device", AsyncMock(return_value=ble_device())
    )
    driver = S4Driver(target, response_timeout=0.1)
    async with driver:
        assert await driver.get_state() == device.state
        # Настоящий разрыв готовой сессии всё ещё завершает слушателя.
        target._on_disconnect(client)
        assert driver._listener is not None
        await asyncio.wait_for(driver._listener, 1)
