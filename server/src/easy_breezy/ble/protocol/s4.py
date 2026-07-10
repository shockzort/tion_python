"""Кодек Tion S4: состояние, разбор ответов, кодирование запросов.

Все факты — из docs/protocol/tion-s4-ble.md (§1.4–1.6). Случайные байты
кадров инжектируются вызывающим — функции детерминированы.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from easy_breezy.ble.protocol.framing import Frame, ProtocolError, build_frame

# GATT (происхождение и статус — спека §1.1; подтверждение на железе — §4 п.1)
GATT_SERVICE = "98f00001-3788-83ea-453e-f52244709ddb"
GATT_WRITE = "98f00002-3788-83ea-453e-f52244709ddb"
GATT_NOTIFY = "98f00003-3788-83ea-453e-f52244709ddb"

OPCODE_REQUEST_PARAMS = b"\x32\x32"
OPCODE_SET_PARAMS = b"\x30\x32"
OPCODE_REQUEST_DEVICE_INFO = b"\x32\x33"
OPCODE_STATE_RESPONSE = b"\x31\x32"

MIN_STATE_PAYLOAD = 20  # известные поля лежат в первых 20 байтах
_SIGN = (181).to_bytes(2, "little")  # константа апстрима, назначение неизвестно

FAN_SPEED_MIN = 1
FAN_SPEED_MAX = 6
HEATER_TEMP_MIN = 0
HEATER_TEMP_MAX = 30


class DecodeError(ProtocolError):
    """Payload не разбирается как состояние S4."""


class Mode(StrEnum):
    """Режим забора воздуха (wire: 0 — приток, 1 — рециркуляция)."""

    OUTSIDE = "outside"
    RECIRCULATION = "recirculation"


@dataclass(frozen=True, slots=True)
class S4State:
    """Состояние бризера S4 (подтверждённые поля спеки §1.5)."""

    power: bool
    sound: bool
    light: bool
    heater: bool
    mode: Mode
    heater_temp: int
    fan_speed: int
    in_temp: int
    out_temp: int
    filter_remain_seconds: int

    @property
    def filter_remain_days(self) -> float:
        return self.filter_remain_seconds / 86400


def _int8(raw: int) -> int:
    return raw - 256 if raw >= 0x80 else raw


def decode_state(payload: bytes) -> S4State:
    """Разбирает payload ответа состояния (терпим к длинному хвосту)."""
    if len(payload) < MIN_STATE_PAYLOAD:
        raise DecodeError(
            f"payload состояния короче {MIN_STATE_PAYLOAD} байт: {len(payload)}"
        )
    flags = payload[0]
    return S4State(
        power=bool(flags & 1),
        sound=bool(flags >> 1 & 1),
        light=bool(flags >> 2 & 1),
        heater=(flags >> 4 & 1) == 0,  # бит ИНВЕРТИРОВАН (спека §1.5)
        mode=Mode.RECIRCULATION if payload[2] == 1 else Mode.OUTSIDE,
        heater_temp=payload[3],
        fan_speed=payload[4],
        in_temp=_int8(payload[5]),
        out_temp=_int8(payload[6]),
        filter_remain_seconds=int.from_bytes(payload[17:20], "little"),
    )


def is_state_response(frame: Frame) -> bool:
    return frame.opcode == OPCODE_STATE_RESPONSE and len(frame.payload) >= (
        MIN_STATE_PAYLOAD
    )


def encode_request_params(*, rand: int, request_id: bytes, extra: bytes) -> bytes:
    """Кадр запроса состояния (REQUEST_PARAMS)."""
    return build_frame(
        OPCODE_REQUEST_PARAMS, rand=rand, request_id=request_id, extra=extra
    )


def encode_set_params(
    state: S4State, *, rand: int, request_id: bytes, extra: bytes
) -> bytes:
    """Кадр установки параметров.

    SET_PARAMS задаёт полный набор параметров разом — ``state`` обязан быть
    полным желаемым состоянием (мерж дельты — забота вызывающего).
    """
    if not FAN_SPEED_MIN <= state.fan_speed <= FAN_SPEED_MAX:
        raise ValueError(f"скорость вне диапазона 1–6: {state.fan_speed}")
    if not HEATER_TEMP_MIN <= state.heater_temp <= HEATER_TEMP_MAX:
        raise ValueError(f"температура вне диапазона 0–30: {state.heater_temp}")

    # Запись: heater — бит 3 (инвертирован), бит 4 — константа 1 (спека §1.6)
    flags = (
        int(state.power)
        | int(state.sound) << 1
        | int(state.light) << 2
        | int(not state.heater) << 3
        | 1 << 4
    )
    mode_code = 1 if state.mode is Mode.RECIRCULATION else 0
    payload = (
        bytes([flags, 0x00, mode_code, state.heater_temp, state.fan_speed]) + _SIGN
    )
    return build_frame(
        OPCODE_SET_PARAMS, payload, rand=rand, request_id=request_id, extra=extra
    )


def encode_request_device_info(*, rand: int, request_id: bytes, extra: bytes) -> bytes:
    """Кадр запроса информации об устройстве (формат ответа — TBD, спека §1.4)."""
    return build_frame(
        OPCODE_REQUEST_DEVICE_INFO, rand=rand, request_id=request_id, extra=extra
    )


def encode_state_payload(state: S4State) -> bytes:
    """Payload ответа состояния — обратная операция к ``decode_state``.

    Устройство такое не принимает — функция нужна эмулятору (FakeS4Device)
    и roundtrip-тестам; неизвестные байты заполняются нулями.
    """
    flags = (
        int(state.power)
        | int(state.sound) << 1
        | int(state.light) << 2
        | int(not state.heater) << 4  # чтение: heater — бит 4, инвертирован
    )
    mode_code = 1 if state.mode is Mode.RECIRCULATION else 0
    payload = bytearray(31)
    payload[0] = flags
    payload[2] = mode_code
    payload[3] = state.heater_temp
    payload[4] = state.fan_speed
    payload[5] = state.in_temp & 0xFF
    payload[6] = state.out_temp & 0xFF
    payload[17:20] = state.filter_remain_seconds.to_bytes(3, "little")
    return bytes(payload)
