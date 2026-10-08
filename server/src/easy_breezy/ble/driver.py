"""Драйвер Tion S4: запрос/ответ поверх транспорта, слушатель нотификаций.

Правила спеки §1.6: SET подтверждается кадром состояния (ожидание с таймаутом,
при тишине — явный REQUEST_PARAMS). CRC ответов валидируется мягко. Все
операции сериализованы per-device локом — одна GATT-операция в полёте.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections import deque
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

FRAME_WRITE_TIMEOUT = 5.0
RESPONSE_TIMEOUT = 3.0
# GET базы (если нет кэша), SET с необязательным ACK, контрольный GET + запас.
COMMAND_EXECUTE_TIMEOUT = 3 * (FRAME_WRITE_TIMEOUT + RESPONSE_TIMEOUT) + 1
COMMAND_LOCK_TIMEOUT = FRAME_WRITE_TIMEOUT + RESPONSE_TIMEOUT + 1
_CONTROL_FIELDS = (
    "power",
    "sound",
    "light",
    "heater",
    "mode",
    "heater_temp",
    "fan_speed",
)


class _Nonces(NamedTuple):
    rand: int
    request_id: bytes
    extra: bytes


class DriverError(Exception):
    """Сбой драйвера устройства."""


class DriverTimeoutError(DriverError):
    """Устройство не ответило кадром состояния за отведённое время."""


class FilterResetUnconfirmed(DriverError):
    """Запись могла пройти; повторять её автоматически нельзя."""

    def __init__(self, message: str, actual: S4State | None = None) -> None:
        super().__init__(message)
        self.actual = actual


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
        response_timeout: float = RESPONSE_TIMEOUT,
        rng: Callable[[int], bytes] = os.urandom,
    ) -> None:
        self._transport = transport
        self._response_timeout = response_timeout
        self._rng = rng
        self._lock = asyncio.Lock()
        self._reassembler = Reassembler()
        self._listener: asyncio.Task[None] | None = None
        self._state_waiter: asyncio.Future[S4State] | None = None
        self._request_id: bytes | None = None
        self._request_started = 0.0
        self._request_kind: str | None = None
        self._retired_ids: deque[bytes] = deque(maxlen=64)
        self.last_state: S4State | None = None
        self.on_state: Callable[[S4State], None] | None = None
        self.on_disconnect: Callable[[], None] | None = None

    @property
    def address(self) -> str:
        return self._transport.address

    async def start(self) -> None:
        try:
            if not self._transport.is_connected:
                await self._transport.connect()
            self._listener = asyncio.create_task(
                self._listen(), name=f"s4-listener-{self.address}"
            )
        except BaseException:
            # В том числе отмена после connect, но до успешного start_notify.
            await self.close()
            raise

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
        Контрольное чтение имеет собственный бюджет ожидания ответа.
        """
        async with self._lock:
            return await self._set_state(desired)

    async def update_state(
        self,
        update: Callable[[S4State], S4State],
        *,
        execute_timeout: float = COMMAND_EXECUTE_TIMEOUT,
    ) -> S4State:
        """Выбирает базу, применяет дельту и подтверждает запись под одним локом.

        Очередь команд уже сериализована шиной: перед ней может быть один
        опрос. Его ожидание имеет отдельный бюджет и не отнимает время GET
        после SET. База выбирается после завершения этого опроса.
        """
        async with asyncio.timeout(FRAME_WRITE_TIMEOUT + self._response_timeout + 1):
            await self._lock.acquire()
        try:
            async with asyncio.timeout(execute_timeout):
                base = self.last_state
                if base is None:
                    base = await self._request_state()
                return await self._set_state(update(base))
        finally:
            self._lock.release()

    async def _set_state(self, desired: S4State) -> S4State:
        nonces = self._nonces()
        waiter = self._new_waiter(nonces.request_id, "set")
        write_error: DriverError | None = None
        try:
            await self._write_frame(
                encode_set_params(
                    desired,
                    rand=nonces.rand,
                    request_id=nonces.request_id,
                    extra=nonces.extra,
                )
            )
            await asyncio.wait_for(waiter, self._response_timeout)
        except TimeoutError:
            log.info(
                "set_confirm_silent",
                address=self.address,
                request_id=nonces.request_id.hex(),
            )
        except DriverError as exc:
            # Запись могла успеть примениться: сначала контрольный GET.
            write_error = exc
            log.warning("set_write_unconfirmed", address=self.address, error=str(exc))
        finally:
            self._finish_waiter(waiter)
        actual = await self._request_state()
        if write_error is not None and not self._controls_match(desired, actual):
            raise write_error
        return actual

    async def _request_state(self) -> S4State:
        nonces = self._nonces()
        waiter = self._new_waiter(nonces.request_id, "get")
        try:
            await self._write_frame(
                encode_request_params(
                    rand=nonces.rand, request_id=nonces.request_id, extra=nonces.extra
                )
            )
            return await asyncio.wait_for(waiter, self._response_timeout)
        except TimeoutError as exc:
            log.warning(
                "state_response_timeout",
                address=self.address,
                request_id=nonces.request_id.hex(),
                response_timeout=self._response_timeout,
            )
            raise DriverTimeoutError(
                f"{self.address}: нет кадра состояния за {self._response_timeout} с"
            ) from exc
        finally:
            self._finish_waiter(waiter)

    async def reset_filter(self, *, expected_days: int | None) -> S4State:
        """Сброс с чтением до/после; настройки сохраняются под одним локом.

        expected_days — результат ранее проверенной прошивки, не параметр SET.
        После возможной записи разрешено только контрольное чтение.
        """
        async with self._lock:
            base = await self._request_state()
            nonces = self._nonces()
            waiter = self._new_waiter(nonces.request_id, "filter_reset")
            try:
                await self._write_frame(
                    encode_set_params(
                        base,
                        rand=nonces.rand,
                        request_id=nonces.request_id,
                        extra=nonces.extra,
                        filter_reset=True,
                    )
                )
                await asyncio.wait_for(waiter, self._response_timeout)
            except (DriverError, TimeoutError):
                log.warning("filter_reset_write_unconfirmed", address=self.address)
            finally:
                self._finish_waiter(waiter)
            try:
                actual = await self._request_state()
            except DriverError as exc:
                raise FilterResetUnconfirmed(
                    "Результат сброса не подтверждён: нет контрольного состояния. "
                    "Не повторяйте сброс без проверки ресурса."
                ) from exc
            settings_match = self._controls_match(base, actual)
            remaining = actual.filter_remain_seconds
            log.info(
                "filter_reset_readback",
                address=self.address,
                before_seconds=base.filter_remain_seconds,
                after_seconds=remaining,
                settings_preserved=settings_match,
            )
            if expected_days is None:
                raise FilterResetUnconfirmed(
                    "Контрольное состояние получено. Нужна проверка ресурса "
                    "и настроек перед включением сброса для этой прошивки.",
                    actual,
                )
            if (
                not settings_match
                or not expected_days * 86400 - 120 <= remaining <= expected_days * 86400
            ):
                raise FilterResetUnconfirmed(
                    "Результат сброса не подтверждён: ресурс или настройки "
                    "отличаются от ожидаемых. Проверьте состояние бризера.",
                    actual,
                )
            return actual

    @staticmethod
    def _controls_match(expected: S4State, actual: S4State) -> bool:
        return all(getattr(expected, f) == getattr(actual, f) for f in _CONTROL_FIELDS)

    def _new_waiter(self, request_id: bytes, kind: str) -> asyncio.Future[S4State]:
        waiter: asyncio.Future[S4State] = asyncio.get_running_loop().create_future()
        self._state_waiter = waiter
        self._request_id = request_id
        self._request_kind = kind
        self._request_started = asyncio.get_running_loop().time()
        return waiter

    def _finish_waiter(self, waiter: asyncio.Future[S4State]) -> None:
        if not waiter.done():
            waiter.cancel()
        elif not waiter.cancelled():
            # Разрыв мог завершить waiter ошибкой одновременно со сбоем write.
            waiter.exception()
        if self._request_id is not None:
            self._retired_ids.append(self._request_id)
        self._state_waiter = None
        self._request_id = None
        self._request_kind = None

    def _nonces(self) -> _Nonces:
        return _Nonces(
            rand=self._rng(1)[0], request_id=self._rng(4), extra=self._rng(4)
        )

    async def _write_frame(self, frame: bytes) -> None:
        try:
            async with asyncio.timeout(FRAME_WRITE_TIMEOUT):
                for packet in split_frame(frame):
                    log.debug("ble_tx", address=self.address, data=packet.hex())
                    await self._transport.write(packet)
        except (TransportError, TimeoutError) as exc:
            raise DriverError(
                f"{self.address}: запись кадра: {type(exc).__name__}: {exc}"
            ) from exc

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

        waiter = self._state_waiter
        matches = frame.request_id == self._request_id
        if (matches and (waiter is None or waiter.done())) or (
            not matches and frame.request_id in self._retired_ids
        ):
            log.warning(
                "stale_state_ignored",
                address=self.address,
                request_id=frame.request_id.hex(),
                expected_id=self._request_id.hex() if self._request_id else None,
            )
            return
        self.last_state = state
        if matches and waiter is not None and not waiter.done():
            log.info(
                "state_response",
                address=self.address,
                request_id=frame.request_id.hex(),
                operation=self._request_kind,
                elapsed_ms=round(
                    (asyncio.get_running_loop().time() - self._request_started) * 1000
                ),
            )
            waiter.set_result(state)
        if self.on_state is not None:
            self.on_state(state)
