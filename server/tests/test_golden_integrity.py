"""Целостность golden-векторов протокола.

Кодек Фазы 1 обязан проходить эти файлы байт-в-байт; здесь проверяется,
что сами векторы согласованы: hex-поля разбираются, длины и CRC сходятся.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

GOLDEN_DIR = Path(__file__).parent / "golden"


def _crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = (
                ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
            )
    return crc


def _unhex(text: str) -> bytes:
    return bytes.fromhex(text.replace(" ", ""))


@pytest.mark.parametrize(
    "name",
    [
        "s4_status_response.json",
        "lite_status_response.json",
        "s3_status_response.json",
        "s4_requests.json",
    ],
)
def test_golden_file_parses(name: str) -> None:
    data = json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))
    assert data["description"]


@pytest.mark.parametrize(
    "name", ["s4_status_response.json", "lite_status_response.json"]
)
def test_lite_family_frame_consistency(name: str) -> None:
    data = json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))
    frame = _unhex(data["frame_hex"])

    # сборка из пакетов: конкатенация без транспортного типового байта
    assembled = b"".join(_unhex(p)[1:] for p in data["ble_packets_hex"])
    assert assembled == frame

    length = int.from_bytes(frame[0:2], "little")
    assert length == len(frame)
    assert frame[2] == 0x3A  # magic
    assert frame[14:-2] == _unhex(data["payload_hex"])
    assert frame[-2:] == _unhex(data["crc_hex"])
    assert int.from_bytes(frame[-2:], "big") == _crc16_ccitt_false(frame[:-2])


def test_s4_request_vectors_consistency() -> None:
    data = json.loads((GOLDEN_DIR / "s4_requests.json").read_text(encoding="utf-8"))
    for key in ("get_status", "set_params"):
        frame = _unhex(data[key]["frame_hex"])
        assert int.from_bytes(frame[0:2], "little") == len(frame)
        assert int.from_bytes(frame[-2:], "big") == _crc16_ccitt_false(frame[:-2])
