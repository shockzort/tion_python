"""UDP-транспорт miIO: hello, нумерация сообщений, таймауты, повтор.

Один транспорт — одно устройство и не больше одного запроса в полёте
(устройства на BL602 теряют параллельные кадры). Перед первым запросом и
после сбоя делается hello: он даёт did и stamp устройства, дальше stamp
ведётся локально по монотонным часам. Таймаут запроса — повтор с новым
hello один раз, затем ``MiioTimeoutError``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import structlog

from easy_breezy.integrations.xiaomi.miio import (
    HEADER_SIZE,
    HELLO,
    MiioKey,
    MiioProtocolError,
    decode_packet,
    encode_payload,
    encode_request,
    parse_hello,
)

log = structlog.get_logger(__name__)

PORT = 54321
DEFAULT_TIMEOUT = 3.0

EndpointFactory = Callable[[asyncio.DatagramProtocol], Awaitable[asyncio.BaseTransport]]
"""Открывает UDP-эндпоинт с заданным протоколом (в тестах — фейк)."""


class MiioError(Exception):
    """Сбой обмена с устройством miIO."""


class MiioTimeoutError(MiioError):
    """Устройство не ответило за отведённое время."""


class MiioDeviceError(MiioError):
    """Устройство ответило ошибкой (``{"error": {...}}``)."""


class _Datagrams(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=32)

    def datagram_received(self, data: bytes, addr: Any) -> None:
        if self.queue.full():
            self.queue.get_nowait()  # опоздавшие ответы старых запросов
        self.queue.put_nowait(data)

    def error_received(self, exc: Exception) -> None:
        log.debug("miio_socket_error", error=str(exc))


class MiioTransport:
    """Клиент одного устройства: ``call(method, params) -> result``."""

    def __init__(
        self,
        host: str,
        key: MiioKey,
        *,
        port: int = PORT,
        timeout: float = DEFAULT_TIMEOUT,
        endpoint_factory: EndpointFactory | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        message_id_seed: int | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._key = key
        self._timeout = timeout
        self._endpoint_factory = endpoint_factory or self._open_udp
        self._monotonic = monotonic
        self._lock = asyncio.Lock()
        self._endpoint: asyncio.BaseTransport | None = None
        self._datagrams: _Datagrams | None = None
        self._did: int | None = None
        self._stamp = 0
        self._stamp_at = 0.0
        seed = int(monotonic()) if message_id_seed is None else message_id_seed
        self._message_id = seed % 10000

    @property
    def did(self) -> int | None:
        """did из последнего hello (None — hello ещё не было)."""
        return self._did

    async def _open_udp(
        self, protocol: asyncio.DatagramProtocol
    ) -> asyncio.BaseTransport:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: protocol, remote_addr=(self._host, self._port)
        )
        return transport

    async def _ensure_endpoint(self) -> _Datagrams:
        if self._endpoint is None or self._datagrams is None:
            datagrams = _Datagrams()
            self._endpoint = await self._endpoint_factory(datagrams)
            self._datagrams = datagrams
        return self._datagrams

    def _send(self, data: bytes) -> None:
        assert self._endpoint is not None
        self._endpoint.sendto(data)  # type: ignore[attr-defined]

    async def _receive(self, datagrams: _Datagrams, deadline: float) -> bytes:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise MiioTimeoutError(f"{self._host}: нет ответа за {self._timeout} с")
        try:
            return await asyncio.wait_for(datagrams.queue.get(), remaining)
        except TimeoutError as exc:
            raise MiioTimeoutError(
                f"{self._host}: нет ответа за {self._timeout} с"
            ) from exc

    async def _hello(self, datagrams: _Datagrams) -> None:
        while not datagrams.queue.empty():  # хвосты прошлых обменов
            datagrams.queue.get_nowait()
        self._send(HELLO)
        deadline = self._monotonic() + self._timeout
        while True:
            data = await self._receive(datagrams, deadline)
            if len(data) != HEADER_SIZE:
                continue
            try:
                reply = parse_hello(data)
            except MiioProtocolError:
                continue
            self._did, self._stamp, self._stamp_at = (
                reply.did,
                reply.stamp,
                self._monotonic(),
            )
            log.debug("miio_hello", host=self._host, did=reply.did, stamp=reply.stamp)
            return

    async def _exchange(
        self, datagrams: _Datagrams, method: str, params: list[Any]
    ) -> Any:
        assert self._did is not None
        self._message_id += 1
        message_id = self._message_id
        stamp = self._stamp + int(self._monotonic() - self._stamp_at) + 1
        plain = encode_payload(message_id, method, params)
        self._send(encode_request(self._key, did=self._did, stamp=stamp, plain=plain))
        deadline = self._monotonic() + self._timeout
        while True:
            data = await self._receive(datagrams, deadline)
            if len(data) <= HEADER_SIZE:
                continue
            try:
                packet = decode_packet(self._key, data)
            except MiioProtocolError as exc:
                raise MiioError(f"{self._host}: {exc}") from exc
            if packet.payload.get("id") != message_id:
                continue  # ответ на прежний (повторённый) запрос
            if "error" in packet.payload:
                raise MiioDeviceError(f"{self._host}: {packet.payload['error']}")
            return packet.payload.get("result")

    async def call(self, method: str, params: list[Any] | None = None) -> Any:
        """Запрос с одним повтором по таймауту; результат — поле ``result``."""
        async with self._lock:
            try:
                return await self._call_locked(method, params or [])
            except OSError as exc:  # DNS, «сеть недоступна», ICMP-отказ
                self.close()
                raise MiioError(f"{self._host}: {exc}") from exc

    async def _call_locked(self, method: str, params: list[Any]) -> Any:
        datagrams = await self._ensure_endpoint()
        for attempt in (1, 2):
            try:
                if self._did is None:
                    await self._hello(datagrams)
                return await self._exchange(datagrams, method, params)
            except MiioTimeoutError:
                self._did = None  # следующий заход — с новым hello
                if attempt == 2:
                    raise
                log.debug("miio_retry", host=self._host, method=method)
        raise AssertionError("unreachable")  # pragma: no cover

    def close(self) -> None:
        if self._endpoint is not None:
            self._endpoint.close()
        self._endpoint = None
        self._datagrams = None
        self._did = None
