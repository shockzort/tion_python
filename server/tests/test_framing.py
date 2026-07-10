"""Кадрирование Lite-семейства против golden-векторов и краевых случаев."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from easy_breezy.ble.protocol.framing import (
    FramingError,
    PacketType,
    Reassembler,
    build_frame,
    parse_frame,
    split_frame,
)

GOLDEN = Path(__file__).parent / "golden"


def _unhex(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


def _load(name: str) -> dict:  # type: ignore[type-arg]
    return json.loads((GOLDEN / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name", ["s4_status_response.json", "lite_status_response.json"]
)
def test_reassemble_golden_capture(name: str) -> None:
    data = _load(name)
    reassembler = Reassembler()

    frames = [reassembler.feed(_unhex(p)) for p in data["ble_packets_hex"]]

    assert frames[:-1] == [None] * (len(frames) - 1)
    assert frames[-1] == _unhex(data["frame_hex"])


@pytest.mark.parametrize(
    "name", ["s4_status_response.json", "lite_status_response.json"]
)
def test_parse_golden_frame(name: str) -> None:
    data = _load(name)
    frame = parse_frame(_unhex(data["frame_hex"]))

    header = data["header"]
    assert frame.opcode == _unhex(header["opcode_hex"])
    assert frame.request_id == _unhex(header["request_id_hex"])
    assert frame.extra == _unhex(header["extra_hex"])
    assert frame.rand == int(header["rand"], 16)
    assert frame.payload == _unhex(data["payload_hex"])
    assert frame.crc_ok, "CRC реального захвата обязан сходиться"


def test_parse_detects_bad_crc() -> None:
    raw = bytearray(_unhex(_load("s4_status_response.json")["frame_hex"]))
    raw[-1] ^= 0xFF
    assert parse_frame(bytes(raw)).crc_ok is False


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda raw: raw[:10], "короче минимума"),
        (lambda raw: raw[:-1], "поле длины"),
        (lambda raw: raw[:2] + b"\x00" + raw[3:], "magic"),
    ],
)
def test_parse_structural_errors(mutate, match: str) -> None:  # type: ignore[no-untyped-def]
    raw = _unhex(_load("s4_status_response.json")["frame_hex"])
    with pytest.raises(FramingError, match=match):
        parse_frame(mutate(raw))


def test_split_matches_golden_requests() -> None:
    data = _load("s4_requests.json")
    for key in ("get_status", "set_params"):
        frame = _unhex(data[key]["frame_hex"])
        expected = [_unhex(p) for p in data[key]["ble_packets_hex"]]
        assert split_frame(frame) == expected


def test_split_boundaries() -> None:
    single = split_frame(b"x" * 19)
    assert len(single) == 1
    assert single[0][0] == PacketType.SINGLE

    two = split_frame(b"x" * 20)
    assert [p[0] for p in two] == [PacketType.FIRST, PacketType.END]
    assert len(two[0]) == 20
    assert len(two[1]) == 2


def test_split_feed_roundtrip() -> None:
    frame = build_frame(
        b"\x30\x32",
        bytes(range(60)),
        rand=0x11,
        request_id=b"\x01\x02\x03\x04",
        extra=b"\x05\x06\x07\x08",
    )
    reassembler = Reassembler()
    result = None
    for packet in split_frame(frame):
        result = reassembler.feed(packet)
    assert result == frame
    parsed = parse_frame(frame)
    assert parsed.crc_ok
    assert parsed.payload == bytes(range(60))


def test_orphan_continuation_raises_and_resets() -> None:
    reassembler = Reassembler()
    with pytest.raises(FramingError, match="без начала"):
        reassembler.feed(bytes([PacketType.MIDDLE]) + b"data")
    # после ошибки сборщик работоспособен
    data = _load("s4_status_response.json")
    for packet_hex in data["ble_packets_hex"]:
        frame = reassembler.feed(_unhex(packet_hex))
    assert frame == _unhex(data["frame_hex"])


def test_unknown_packet_type_raises() -> None:
    with pytest.raises(FramingError, match="неизвестный тип"):
        Reassembler().feed(b"\x55data")


def test_new_first_restarts_assembly() -> None:
    data = _load("s4_status_response.json")
    packets = [_unhex(p) for p in data["ble_packets_hex"]]
    reassembler = Reassembler()
    reassembler.feed(packets[0])
    reassembler.feed(packets[1])
    # новый FIRST посреди сборки — старый буфер отброшен
    for packet in packets:
        frame = reassembler.feed(packet)
    assert frame == _unhex(data["frame_hex"])
