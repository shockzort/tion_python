"""Кадрирование Lite-семейства (S4, Lite): пакеты, сборка, CRC.

Формат кадра (без транспортного типового байта):
``[len:2 LE][magic 0x3a][rand:1][opcode:2][request_id:4][extra:4][payload…][crc:2 BE]``
CRC — CRC-16/CCITT-FALSE по кадру без двух байт CRC (спека §1.3).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

MAGIC = 0x3A
HEADER_SIZE = 14  # len(2) + magic(1) + rand(1) + opcode(2) + request_id(4) + extra(4)
CRC_SIZE = 2
MIN_FRAME_SIZE = HEADER_SIZE + CRC_SIZE
MAX_FRAME_SIZE = 1024  # защита сборщика от мусорного потока
_CHUNK_SIZE = 19  # полезных байт в BLE-пакете (20 минус типовой байт)

OPCODE_SIZE = 2
REQUEST_ID_SIZE = 4
EXTRA_SIZE = 4


class PacketType(IntEnum):
    """Первый байт BLE-пакета — положение пакета в кадре."""

    FIRST = 0x00
    MIDDLE = 0x40
    SINGLE = 0x80
    END = 0xC0


class ProtocolError(Exception):
    """Базовая ошибка протокола Tion."""


class FramingError(ProtocolError):
    """Нарушение кадрирования: неожиданный пакет, битая структура кадра."""


def crc16_ccitt_false(data: bytes) -> int:
    """CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF, без отражений и xorout."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = (
                ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
            )
    return crc


@dataclass(frozen=True, slots=True)
class Frame:
    """Разобранный кадр протокола."""

    opcode: bytes
    request_id: bytes
    extra: bytes
    payload: bytes
    rand: int
    crc_ok: bool
    """CRC проверяется мягко (спека §1.3): False — несовпадение, кадр не отброшен."""


def build_frame(
    opcode: bytes,
    payload: bytes = b"",
    *,
    rand: int,
    request_id: bytes,
    extra: bytes,
) -> bytes:
    """Собирает кадр с корректным CRC (в отличие от апстрима с константой)."""
    if len(opcode) != OPCODE_SIZE:
        raise ValueError(f"опкод должен быть {OPCODE_SIZE} байта, получено {opcode!r}")
    if len(request_id) != REQUEST_ID_SIZE or len(extra) != EXTRA_SIZE:
        raise ValueError("request_id и extra должны быть по 4 байта")
    if not 0 <= rand <= 0xFF:
        raise ValueError(f"rand вне диапазона байта: {rand}")

    length = HEADER_SIZE + len(payload) + CRC_SIZE
    body = (
        length.to_bytes(2, "little")
        + bytes([MAGIC, rand])
        + opcode
        + request_id
        + extra
        + payload
    )
    return body + crc16_ccitt_false(body).to_bytes(2, "big")


def parse_frame(raw: bytes) -> Frame:
    """Разбирает собранный кадр; структурные ошибки — FramingError."""
    if len(raw) < MIN_FRAME_SIZE:
        raise FramingError(f"кадр короче минимума: {len(raw)} байт")
    length = int.from_bytes(raw[0:2], "little")
    if length != len(raw):
        raise FramingError(f"поле длины {length} не совпадает с размером {len(raw)}")
    if raw[2] != MAGIC:
        raise FramingError(f"неверный magic: {raw[2]:#04x}")

    crc_ok = int.from_bytes(raw[-2:], "big") == crc16_ccitt_false(raw[:-2])
    return Frame(
        opcode=raw[4:6],
        request_id=raw[6:10],
        extra=raw[10:14],
        payload=raw[14:-CRC_SIZE],
        rand=raw[3],
        crc_ok=crc_ok,
    )


def split_frame(frame: bytes) -> list[bytes]:
    """Режет кадр на BLE-пакеты ≤20 байт с типовыми байтами."""
    if len(frame) <= _CHUNK_SIZE:
        return [bytes([PacketType.SINGLE]) + frame]

    chunks = [frame[i : i + _CHUNK_SIZE] for i in range(0, len(frame), _CHUNK_SIZE)]
    packets: list[bytes] = []
    last = len(chunks) - 1
    for i, chunk in enumerate(chunks):
        if i == 0:
            ptype = PacketType.FIRST
        elif i == last:
            ptype = PacketType.END
        else:
            ptype = PacketType.MIDDLE
        packets.append(bytes([ptype]) + chunk)
    return packets


class Reassembler:
    """Сборщик кадров из потока нотификаций (по одному на устройство).

    ``feed`` возвращает собранный кадр (сырые байты) или ``None``, если кадр
    ещё не полон. Пакет-продолжение без начала — FramingError (буфер сброшен);
    новый FIRST/SINGLE всегда начинает сборку заново (спека §1.2).
    """

    def __init__(self) -> None:
        self._buffer: bytearray | None = None

    def reset(self) -> None:
        self._buffer = None

    def feed(self, packet: bytes) -> bytes | None:
        if not packet:
            raise FramingError("пустой пакет")

        ptype = packet[0]
        if ptype == PacketType.SINGLE:
            self._buffer = None
            return bytes(packet[1:])
        if ptype == PacketType.FIRST:
            self._buffer = bytearray(packet[1:])
            return None
        if ptype in (PacketType.MIDDLE, PacketType.END):
            if self._buffer is None:
                raise FramingError(f"пакет-продолжение {ptype:#04x} без начала кадра")
            self._buffer += packet[1:]
            if len(self._buffer) > MAX_FRAME_SIZE:
                self._buffer = None
                raise FramingError("превышен максимальный размер кадра")
            if ptype == PacketType.END:
                frame = bytes(self._buffer)
                self._buffer = None
                return frame
            return None

        self._buffer = None
        raise FramingError(f"неизвестный тип пакета {ptype:#04x}")
