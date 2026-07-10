"""Эмулятор бризера S4 и фейковый транспорт — тесты и dev-режим без железа."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from easy_breezy.ble.protocol.framing import (
    Frame,
    Reassembler,
    build_frame,
    parse_frame,
    split_frame,
)
from easy_breezy.ble.protocol.s4 import (
    OPCODE_REQUEST_PARAMS,
    OPCODE_SET_PARAMS,
    OPCODE_STATE_RESPONSE,
    Mode,
    S4State,
    encode_state_payload,
)
from easy_breezy.ble.transport import TransportError

DEFAULT_STATE = S4State(
    power=True,
    sound=True,
    light=False,
    heater=False,
    mode=Mode.OUTSIDE,
    heater_temp=20,
    fan_speed=2,
    in_temp=5,
    out_temp=18,
    filter_remain_seconds=180 * 86400,
)


class FakeS4Device:
    """Эмулятор: держит состояние, отвечает кадрами по правилам спеки.

    Инъекция сбоев — через атрибуты (``drop_responses``, ``corrupt_crc``,
    ``push_state_after_set``).
    """

    def __init__(self, state: S4State = DEFAULT_STATE) -> None:
        self.state = state
        self.received_frames: list[Frame] = []
        self.push_state_after_set = True
        """Гипотеза спеки §1.6: устройство шлёт состояние после SET."""
        self.drop_responses = 0
        """Сколько ближайших ответов молча не отправлять (таймауты)."""
        self.corrupt_crc = False
        """Портить CRC ответов (проверка мягкой валидации)."""
        self._reassembler = Reassembler()

    def handle_packet(self, packet: bytes) -> list[bytes]:
        """Принимает пакет запроса, возвращает пакеты ответа (может быть пусто)."""
        raw = self._reassembler.feed(packet)
        if raw is None:
            return []
        frame = parse_frame(raw)
        self.received_frames.append(frame)

        if self.drop_responses > 0:
            self.drop_responses -= 1
            return []
        if frame.opcode == OPCODE_REQUEST_PARAMS:
            return self.state_packets(request_id=frame.request_id)
        if frame.opcode == OPCODE_SET_PARAMS:
            self._apply_set(frame.payload)
            if self.push_state_after_set:
                return self.state_packets(request_id=frame.request_id)
            return []
        return []

    def state_packets(self, request_id: bytes = b"\x00\x00\x00\x00") -> list[bytes]:
        """Кадр текущего состояния, разрезанный на BLE-пакеты."""
        frame = build_frame(
            OPCODE_STATE_RESPONSE,
            encode_state_payload(self.state),
            rand=0x00,
            request_id=request_id,
            extra=b"\x00\x00\x00\x00",
        )
        if self.corrupt_crc:
            frame = frame[:-1] + bytes([frame[-1] ^ 0xFF])
        return split_frame(frame)

    def _apply_set(self, payload: bytes) -> None:
        flags = payload[0]
        self.state = S4State(
            power=bool(flags & 1),
            sound=bool(flags >> 1 & 1),
            light=bool(flags >> 2 & 1),
            heater=not bool(flags >> 3 & 1),  # запись: бит 3, инвертирован
            mode=Mode.RECIRCULATION if payload[2] == 1 else Mode.OUTSIDE,
            heater_temp=payload[3],
            fan_speed=payload[4],
            in_temp=self.state.in_temp,
            out_temp=self.state.out_temp,
            filter_remain_seconds=self.state.filter_remain_seconds,
        )


class FakeTransport:
    """Транспорт, соединяющий драйвер с ``FakeS4Device`` в памяти."""

    def __init__(
        self, device: FakeS4Device, *, address: str = "FA:KE:00:00:00:01"
    ) -> None:
        self.device = device
        self._address = address
        self._connected = False
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.connect_failures = 0
        """Сколько ближайших connect() должны упасть (тесты реконнекта)."""
        self.fail_writes = False
        self.paired = False
        self.connect_count = 0

    @property
    def address(self) -> str:
        return self._address

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> None:
        self.connect_count += 1
        if self.connect_failures > 0:
            self.connect_failures -= 1
            raise TransportError("нет связи (фейк)")
        self._queue = asyncio.Queue()
        self._connected = True

    async def disconnect(self) -> None:
        if self._connected:
            self._connected = False
            self._queue.put_nowait(None)

    async def write(self, packet: bytes) -> None:
        if not self._connected:
            raise TransportError("запись без соединения (фейк)")
        if self.fail_writes:
            raise TransportError("сбой записи (фейк)")
        for response in self.device.handle_packet(packet):
            self._queue.put_nowait(response)

    async def notifications(self) -> AsyncIterator[bytes]:
        while True:
            packet = await self._queue.get()
            if packet is None:
                return
            yield packet

    async def pair(self) -> None:
        self.paired = True

    async def unpair(self) -> None:
        self.paired = False

    def push_state(self) -> None:
        """Незапрошенный кадр состояния (push устройства)."""
        for packet in self.device.state_packets():
            self._queue.put_nowait(packet)

    def simulate_connection_loss(self) -> None:
        self._connected = False
        self._queue.put_nowait(None)
