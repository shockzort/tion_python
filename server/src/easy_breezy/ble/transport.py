"""Транспортная абстракция BLE и реализация на Bleak.

Транспорт переносит сырые пакеты (≤20 байт) в обе стороны и ничего не знает
о кадрах — кадрирование живёт в ``ble.protocol``. Абстракция допускает
будущие реализации (BLE-прокси, эмулятор).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

import structlog
from bleak import BleakClient
from bleak.exc import BleakError

log = structlog.get_logger("easy_breezy.ble")


class TransportError(Exception):
    """Сбой BLE-транспорта (соединение, запись, сопряжение)."""


class BleTransport(Protocol):
    """Контракт транспорта: подключение, запись пакетов, поток нотификаций."""

    @property
    def address(self) -> str: ...

    @property
    def is_connected(self) -> bool: ...

    async def connect(self) -> None: ...

    async def disconnect(self) -> None: ...

    async def write(self, packet: bytes) -> None: ...

    def notifications(self) -> AsyncIterator[bytes]:
        """Поток входящих пакетов; завершается при разрыве соединения."""
        ...

    async def pair(self) -> None: ...

    async def unpair(self) -> None: ...


class BleakTransport:
    """Транспорт поверх BleakClient (BlueZ).

    Экземпляр одноразовый: после разрыва создаётся новый (фабрика в
    супервизоре) — это обходит невозобновляемость BleakClient.
    """

    def __init__(
        self,
        address: str,
        *,
        notify_uuid: str,
        write_uuid: str,
        connect_timeout: float = 10.0,
        operation_timeout: float = 5.0,
    ) -> None:
        self._address = address
        self._notify_uuid = notify_uuid
        self._write_uuid = write_uuid
        self._connect_timeout = connect_timeout
        self._operation_timeout = operation_timeout
        self._client = BleakClient(
            address,
            disconnected_callback=self._on_disconnect,
            timeout=connect_timeout,
        )
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    @property
    def address(self) -> str:
        return self._address

    @property
    def is_connected(self) -> bool:
        return bool(self._client.is_connected)

    async def connect(self) -> None:
        self._queue = asyncio.Queue()
        try:
            async with asyncio.timeout(self._connect_timeout + 5):
                await self._client.connect()
                await self._client.start_notify(self._notify_uuid, self._on_notify)
        except (BleakError, TimeoutError, OSError) as exc:
            raise TransportError(f"подключение к {self._address}: {exc}") from exc
        log.debug("transport_connected", address=self._address)

    async def disconnect(self) -> None:
        try:
            async with asyncio.timeout(self._operation_timeout * 2):
                await self._client.disconnect()
        except (BleakError, TimeoutError, OSError) as exc:
            log.warning(
                "transport_disconnect_failed", address=self._address, error=str(exc)
            )
        finally:
            self._queue.put_nowait(None)

    async def write(self, packet: bytes) -> None:
        try:
            async with asyncio.timeout(self._operation_timeout):
                await self._client.write_gatt_char(
                    self._write_uuid, packet, response=False
                )
        except (BleakError, TimeoutError, OSError) as exc:
            raise TransportError(f"запись в {self._address}: {exc}") from exc

    async def notifications(self) -> AsyncIterator[bytes]:
        while True:
            packet = await self._queue.get()
            if packet is None:
                return
            yield packet

    async def pair(self) -> None:
        """OS-уровневое сопряжение (S4 не требует прикладного кадра, спека §1.7)."""
        try:
            async with asyncio.timeout(30.0):
                await self._client.pair()
        except (BleakError, TimeoutError, OSError) as exc:
            raise TransportError(f"сопряжение с {self._address}: {exc}") from exc

    async def unpair(self) -> None:
        try:
            async with asyncio.timeout(self._operation_timeout * 2):
                await self._client.unpair()
        except (BleakError, TimeoutError, OSError) as exc:
            raise TransportError(f"отвязка {self._address}: {exc}") from exc

    def _on_notify(self, _char: object, data: bytearray) -> None:
        log.debug("ble_rx", address=self._address, data=bytes(data).hex())
        self._queue.put_nowait(bytes(data))

    def _on_disconnect(self, _client: BleakClient) -> None:
        log.debug("ble_disconnected", address=self._address)
        self._queue.put_nowait(None)
