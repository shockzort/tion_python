"""Кодек S4 против golden-векторов: decode и encode байт-в-байт."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from easy_breezy.ble.protocol.framing import parse_frame
from easy_breezy.ble.protocol.s4 import (
    DecodeError,
    Mode,
    S4State,
    decode_state,
    encode_request_params,
    encode_set_params,
    is_state_response,
)

GOLDEN = Path(__file__).parent / "golden"


def _unhex(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


def _load(name: str) -> dict:  # type: ignore[type-arg]
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


@pytest.fixture
def nonces() -> dict[str, bytes | int]:
    raw = _load("s4_requests.json")["nonces"]
    return {
        "rand": int(raw["rand"], 16),
        "request_id": _unhex(raw["request_id_hex"]),
        "extra": _unhex(raw["extra_hex"]),
    }


def test_decode_golden_state() -> None:
    data = _load("s4_status_response.json")
    state = decode_state(_unhex(data["payload_hex"]))

    decoded = dataclasses.asdict(state)
    for field, expected in data["expected_state"].items():
        assert decoded[field] == expected, field
    assert state.filter_remain_days == pytest.approx(174.456, abs=0.001)


def test_state_response_detection() -> None:
    data = _load("s4_status_response.json")
    frame = parse_frame(_unhex(data["frame_hex"]))
    assert is_state_response(frame)


def test_decode_short_payload_raises() -> None:
    with pytest.raises(DecodeError, match="короче"):
        decode_state(bytes(19))


def test_encode_request_params_golden(nonces: dict[str, bytes | int]) -> None:
    data = _load("s4_requests.json")["get_status"]
    frame = encode_request_params(**nonces)  # type: ignore[arg-type]
    assert frame == _unhex(data["frame_hex"])


def _golden_set_state() -> S4State:
    fields = _load("s4_requests.json")["set_params"]["fields"]
    return S4State(
        power=fields["power"],
        sound=fields["sound"],
        light=fields["light"],
        heater=fields["heater"],
        mode=Mode(fields["mode"]),
        heater_temp=fields["heater_temp"],
        fan_speed=fields["fan_speed"],
        in_temp=0,
        out_temp=0,
        filter_remain_seconds=0,
    )


def test_encode_set_params_golden(nonces: dict[str, bytes | int]) -> None:
    data = _load("s4_requests.json")["set_params"]
    frame = encode_set_params(_golden_set_state(), **nonces)  # type: ignore[arg-type]
    assert frame == _unhex(data["frame_hex"])


def test_set_roundtrip_via_fake_flags(nonces: dict[str, bytes | int]) -> None:
    """Кодируем SET → биты флагов запроса соответствуют спеке §1.6."""
    state = _golden_set_state()
    frame = parse_frame(encode_set_params(state, **nonces))  # type: ignore[arg-type]
    flags = frame.payload[0]
    assert bool(flags & 1) is state.power
    assert bool(flags >> 1 & 1) is state.sound
    assert bool(flags >> 2 & 1) is state.light
    assert bool(flags >> 3 & 1) is (not state.heater)  # инверсия записи
    assert flags >> 4 & 1 == 1  # константный бит


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("fan_speed", 0, "скорость"),
        ("fan_speed", 7, "скорость"),
        ("heater_temp", 31, "температура"),
        ("heater_temp", -1, "температура"),
    ],
)
def test_encode_set_validation(
    field: str, value: int, match: str, nonces: dict[str, bytes | int]
) -> None:
    state = dataclasses.replace(_golden_set_state(), **{field: value})
    with pytest.raises(ValueError, match=match):
        encode_set_params(state, **nonces)  # type: ignore[arg-type]


def test_decode_mode_fallback_to_outside() -> None:
    """Wire-код режима ≥2 трактуем как приток (совместимость с Lite-нумерацией)."""
    payload = bytearray(_unhex(_load("s4_status_response.json")["payload_hex"]))
    payload[2] = 5
    assert decode_state(bytes(payload)).mode is Mode.OUTSIDE
