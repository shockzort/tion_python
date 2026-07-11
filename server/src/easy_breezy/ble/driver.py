"""Драйвер Tion S4: запрос/ответ поверх транспорта, слушатель нотификаций.

Правила спеки §1.6: SET подтверждается кадром состояния (ожидание с таймаутом,
при тишине — явный REQUEST_PARAMS). CRC ответов валидируется мягко. Все
операции сериализованы per-device локом — одна GATT-операция в полёте.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import Callable
from typing import NamedTuple, Self

import structlog

from easy_breezy.ble.protocol.framing import (
    FramingError,
    Reassembler,
    parse_frame,
    split_frame,
)
from easy_breezy.ble.protocol.s4 import (
    DecodeError,
    S4State,
    decode_state,
    encode_request_params,
    encode_set_params,
    is_state_response,
)
from easy_breezy.ble.transport import BleTransport, TransportError

log = structlog.get_logger("easy_breezy.ble")


class _Nonces(NamedTuple):
    rand: int
    request_id: bytes
    extra: bytes


class DriverError(Exception):
    """Сбой драйвера устройства."""


class DriverTimeoutError(DriverError):
    """Устройство не ответило кадром состояния за отведённое время."""


class S4Driver:
    """Драйвер одного бризера S4.

    Жизненный цикл: ``start()`` подключает транспорт и запускает слушатель;
    ``close()`` останавливает. Колбэки ``on_state``/``on_disconnect``
    назначает владелец (супервизор) — вызываются из задачи слушателя.
    """

    def __init__(
        self,
        transport: BleTransport,
        *,
        response_timeout: float = 3.0,
        rng: Callable[[int], bytes] = os.urandom,
    ) -> None:
        self._transport = transport
        self._response_timeout = response_timeout
        self._rng = rng
        self._lock = asyncio.Lock()
        self._reassembler = Reassembler()
        self._listener: asyncio.Task[None] | None = None
        self._state_waiter: asyncio.Future[S4State] | None = None
        self.last_state: S4State | None = None
        self.on_state: Callable[[S4State], None] | None = None
        self.on_disconnect: Callable[[], None] | None = None

    @property
    def address(self) -> str:
        return self._transport.address

    async def start(self) -> None:
        if not self._transport.is_connected:
            await self._transport.connect()
        self._listener = asyncio.create_task(
            self._listen(), name=f"s4-listener-{self.address}"
        )

    async def close(self) -> None:
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener
            self._listener = None
        try:
            await self._transport.disconnect()
        except TransportError as exc:
            log.warning("driver_close_failed", address=self.address, error=str(exc))

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    async def get_state(self) -> S4State:
        """Запрашивает состояние (REQUEST_PARAMS) и ждёт кадр ответа."""
        async with self._lock:
            return await self._request_state()

    async def set_state(self, desired: S4State) -> S4State:
        """Пишет полный набор параметров, возвращает фактическое состояние.

        После подтверждения (или тишины) всегда выполняется контрольный
        REQUEST_PARAMS: кадр вслед за SET может потеряться при сборке
        (флаки BLE), а прошивка вправе скорректировать запрошенные поля
        (полевой факт: включение рециркуляции меняет fan_speed — спека §1.6).
        Контрольный запрос дёшев (~150 мс) и возвращает истину устройства.
        """
        async with self._lock:
            waiter = self._new_waiter()
            nonces = self._nonces()
            await self._write_frame(
                encode_set_params(
                    desired,
                    rand=nonces.rand,
                    request_id=nonces.request_id,
                    extra=nonces.extra,
                )
            )
            try:
                await asyncio.wait_for(waiter, self._response_timeout)
            except TimeoutError:
                log.debug("set_confirm_silent", address=self.address)
            finally:
                self._state_waiter = None
            return await self._request_state()

    async def _request_state(self) -> S4State:
        waiter = self._new_waiter()
        nonces = self._nonces()
        await self._write_frame(
            encode_request_params(
                rand=nonces.rand, request_id=nonces.request_id, extra=nonces.extra
            )
        )
        try:
            return await asyncio.wait_for(waiter, self._response_timeout)
        except TimeoutError as exc:
            raise DriverTimeoutError(
                f"{self.address}: нет кадра состояния за {self._response_timeout} с"
            ) from exc
        finally:
            self._state_waiter = None

    def _new_waiter(self) -> asyncio.Future[S4State]:
        waiter: asyncio.Future[S4State] = asyncio.get_running_loop().create_future()
        self._state_waiter = waiter
        return waiter

    def _nonces(self) -> _Nonces:
        return _Nonces(
            rand=self._rng(1)[0], request_id=self._rng(4), extra=self._rng(4)
        )

    async def _write_frame(self, frame: bytes) -> None:
        try:
            for packet in split_frame(frame):
                log.debug("ble_tx", address=self.address, data=packet.hex())
                await self._transport.write(packet)
        except TransportError as exc:
            raise DriverError(f"{self.address}: {exc}") from exc

    async def _listen(self) -> None:
        try:
            async for packet in self._transport.notifications():
                self._handle_packet(packet)
        finally:
            waiter = self._state_waiter
            if waiter is not None and not waiter.done():
                waiter.set_exception(
                    DriverError(f"{self.address}: соединение разорвано")
                )
            if self.on_disconnect is not None:
                self.on_disconnect()

    def _handle_packet(self, packet: bytes) -> None:
        try:
            raw = self._reassembler.feed(packet)
        except FramingError as exc:
            log.warning("framing_error", address=self.address, error=str(exc))
            return
        if raw is None:
            return
        try:
            frame = parse_frame(raw)
        except FramingError as exc:
            log.warning("bad_frame", address=self.address, error=str(exc))
            return
        if not frame.crc_ok:
            # мягкий режим до полевого подтверждения CRC (спека §1.3)
            log.warning("crc_mismatch", address=self.address, frame=raw.hex())
        if not is_state_response(frame):
            log.debug("frame_ignored", address=self.address, opcode=frame.opcode.hex())
            return
        try:
            state = decode_state(frame.payload)
        except DecodeError as exc:
            log.warning("state_decode_failed", address=self.address, error=str(exc))
            return

        self.last_state = state
        waiter = self._state_waiter
        if waiter is not None and not waiter.done():
            waiter.set_result(state)
        if self.on_state is not None:
            self.on_state(state)
