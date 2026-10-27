"""miIO: golden-кадры кодека, модель ha2, UDP-транспорт на фейке."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from easy_breezy.integrations.xiaomi import ha2
from easy_breezy.integrations.xiaomi.ha2 import ApplianceDeltaError, Ha2Delta
from easy_breezy.integrations.xiaomi.miio import (
    HELLO,
    MiioKey,
    MiioProtocolError,
    decode_packet,
    encode_request,
    parse_hello,
)
from easy_breezy.integrations.xiaomi.transport import (
    MiioDeviceError,
    MiioError,
    MiioTimeoutError,
    MiioTransport,
)
from tests.fake_miio import HA2_VALUES, FakeMiioDevice, fake_transport

GOLDEN = json.loads(
    (Path(__file__).parent / "golden" / "miio_frames.json").read_text(encoding="utf-8")
)
KEY = MiioKey.from_hex(GOLDEN["token"])


# --- кодек: golden --------------------------------------------------------------


def test_hello_matches_golden() -> None:
    assert HELLO.hex() == GOLDEN["hello_request"]
    reply = parse_hello(bytes.fromhex(GOLDEN["hello_response"]))
    assert reply.did == GOLDEN["did"]
    assert reply.stamp == 0x600


def test_encode_request_matches_golden_byte_for_byte() -> None:
    request = GOLDEN["request"]
    frame = encode_request(
        KEY, did=GOLDEN["did"], stamp=request["stamp"], plain=request["plain"].encode()
    )
    assert frame.hex() == request["frame"]


def test_decode_response_golden() -> None:
    response = GOLDEN["response"]
    packet = decode_packet(KEY, bytes.fromhex(response["frame"]))
    assert packet.did == GOLDEN["did"]
    assert packet.stamp == response["stamp"]
    assert packet.payload == json.loads(response["plain"])
    assert packet.payload["result"][2]["value"] == 24.0


def test_decode_rejects_wrong_token() -> None:
    other = MiioKey.from_hex("ff" * 16)
    with pytest.raises(MiioProtocolError, match="контрольная сумма"):
        decode_packet(other, bytes.fromhex(GOLDEN["response"]["frame"]))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda b: b"\x21\x32" + b[2:], "magic"),
        (lambda b: b[:-16], "длина"),
        (lambda b: b[:10], "короче"),
    ],
)
def test_decode_rejects_broken_frames(mutate: Any, message: str) -> None:
    frame = bytes.fromhex(GOLDEN["response"]["frame"])
    with pytest.raises(MiioProtocolError, match=message):
        decode_packet(KEY, mutate(frame))


def test_token_must_be_16_bytes() -> None:
    with pytest.raises(ValueError, match="32 hex"):
        MiioKey.from_hex("abcd")


# --- модель ha2 ------------------------------------------------------------------


def _result(values: dict[tuple[int, int], Any]) -> list[dict[str, Any]]:
    return [
        {"did": f"{s}-{p}", "siid": s, "piid": p, "code": 0, "value": v}
        for (s, p), v in values.items()
    ]


def test_parse_properties_owner_snapshot() -> None:
    state = ha2.parse_properties(_result(HA2_VALUES))
    assert state.power is True
    assert state.function == "humidify"
    assert state.humidifier_mode == "fan"
    assert state.humidifier_fan_level == 1  # 0 на устройстве → 1 в сервисе
    assert state.target_humidity == 55
    assert state.water_state == "normal"
    assert state.sensor_metrics() == {
        "humidity": 55.0,
        "temperature": 24.0,
        "pm25": 3.0,
    }


def test_parse_properties_missing_is_error() -> None:
    values = dict(HA2_VALUES)
    del values[(3, 1)]
    with pytest.raises(ApplianceDeltaError, match="humidity"):
        ha2.parse_properties(_result(values))


def test_parse_properties_ignores_failed_codes() -> None:
    result = _result(HA2_VALUES)
    result[0] = {**result[0], "code": -4001}
    with pytest.raises(ApplianceDeltaError, match="power"):
        ha2.parse_properties(result)


def test_delta_to_properties_function_first_and_levels_shifted() -> None:
    delta = Ha2Delta.from_payload(
        {"humidifier_fan_level": 3, "function": "purify", "target_humidity": 60}
    )
    props = delta.to_properties()
    assert [p["did"] for p in props] == [
        "function",
        "target_humidity",
        "humidifier_fan_level",
    ]
    assert props[0] == {"did": "function", "siid": 9, "piid": 5, "value": 0}
    assert props[2]["value"] == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"target_humidity": 80},
        {"target_humidity": True},
        {"humidifier_fan_level": 0},
        {"function": "dry"},
        {"power": 1},
        {"turbo": True},
    ],
)
def test_delta_validation(payload: dict[str, Any]) -> None:
    with pytest.raises(ApplianceDeltaError):
        Ha2Delta.from_payload(payload)


# --- транспорт -------------------------------------------------------------------


async def test_transport_hello_then_call() -> None:
    device = FakeMiioDevice()
    transport = fake_transport(device)
    result = await transport.call("get_properties", ha2.property_request()[:10])
    assert len(result) == 10
    assert device.hellos == 1
    assert transport.did == device.did
    await transport.call("get_properties", ha2.property_request()[10:])
    assert device.hellos == 1  # сессия живёт — повторный hello не нужен
    ids = [request["id"] for request in device.requests]
    assert ids == sorted(set(ids))


async def test_transport_retries_once_with_new_hello() -> None:
    device = FakeMiioDevice(drop=1)
    transport = fake_transport(device)
    result = await transport.call("get_properties", ha2.property_request()[:2])
    assert len(result) == 2
    assert device.hellos == 2


async def test_transport_gives_up_after_second_timeout() -> None:
    device = FakeMiioDevice(drop=2)
    transport = fake_transport(device)
    with pytest.raises(MiioTimeoutError):
        await transport.call("get_properties", ha2.property_request()[:2])


async def test_transport_device_error() -> None:
    transport = fake_transport(FakeMiioDevice())
    with pytest.raises(MiioDeviceError, match="-9999"):
        await transport.call("miIO.unknown")


async def test_transport_wraps_os_errors() -> None:
    async def broken(_protocol: Any) -> Any:
        raise OSError(-3, "Temporary failure in name resolution")

    transport = MiioTransport("nowhere", KEY, endpoint_factory=broken, timeout=0.05)
    with pytest.raises(MiioError, match="name resolution"):
        await transport.call("miIO.info")
