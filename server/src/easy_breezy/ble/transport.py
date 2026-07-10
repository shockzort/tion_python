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
from bleak import BleakClient, BleakScanner
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
        self._client: BleakClient | None = None
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()

    @property
    def address(self) -> str:
        return self._address

    @property
    def is_connected(self) -> bool:
        return self._client is not None and bool(self._client.is_connected)

    def _require_client(self) -> BleakClient:
        if self._client is None:
            raise TransportError(f"{self._address}: транспорт не подключён")
        return self._client

    async def connect(self) -> None:
        """Поиск устройства в эфире и подключение по объекту (паттерн BlueZ).

        Подключение по «голому» адресу ненадёжно (полевой факт смоука Фазы 1) —
        сначала find_device_by_address, затем connect по BLEDevice.
        """
        self._queue = asyncio.Queue()
        try:
            async with asyncio.timeout(15.0):
                device = await BleakScanner.find_device_by_address(
                    self._address, timeout=14.0
                )
        except (BleakError, TimeoutError, OSError) as exc:
            raise TransportError(f"поиск {self._address} в эфире: {exc}") from exc
        if device is None:
            raise TransportError(f"{self._address} не найден в эфире")
        log.debug("device_found", address=self._address, rssi=None)

        self._client = BleakClient(
            device,
            disconnected_callback=self._on_disconnect,
            timeout=self._connect_timeout,
        )
        try:
            async with asyncio.timeout(self._connect_timeout + 10):
                await self._client.connect()
        except (BleakError, TimeoutError, OSError) as exc:
            raise TransportError(
                f"LE-соединение с {self._address} не установлено "
                f"(таймаут {self._connect_timeout} c): {exc}"
            ) from exc
        log.debug("le_connected", address=self._address)

        try:
            async with asyncio.timeout(self._operation_timeout * 2):
                await self._client.start_notify(self._notify_uuid, self._on_notify)
        except (BleakError, TimeoutError, OSError) as exc:
            raise TransportError(
                f"подписка на нотификации {self._address}: {exc}"
            ) from exc
        log.debug("transport_connected", address=self._address)

    async def disconnect(self) -> None:
        if self._client is None:
            return
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
                await self._require_client().write_gatt_char(
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
                await self._require_client().pair()
        except (BleakError, TimeoutError, OSError) as exc:
            raise TransportError(f"сопряжение с {self._address}: {exc}") from exc

    async def unpair(self) -> None:
        """Удаление бонда; работает и без активного соединения (BlueZ)."""
        client = self._client or BleakClient(self._address)
        try:
            async with asyncio.timeout(self._operation_timeout * 2):
                await client.unpair()
        except (BleakError, TimeoutError, OSError) as exc:
            raise TransportError(f"отвязка {self._address}: {exc}") from exc

    def _on_notify(self, _char: object, data: bytearray) -> None:
        log.debug("ble_rx", address=self._address, data=bytes(data).hex())
        self._queue.put_nowait(bytes(data))

    def _on_disconnect(self, _client: BleakClient) -> None:
        log.debug("ble_disconnected", address=self._address)
        self._queue.put_nowait(None)
