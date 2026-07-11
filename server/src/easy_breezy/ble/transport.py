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
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus

from easy_breezy.ble._bluez_agent import AGENT_CAPABILITY, AGENT_PATH, JustWorksAgent

log = structlog.get_logger("easy_breezy.ble")

_BLUEZ_ALREADY_EXISTS = "org.bluez.Error.AlreadyExists"


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
        device = await self._find_device()
        await self._attach(device)

    async def _find_device(self) -> BLEDevice:
        """Найти устройство в эфире; занятый другим центральным не рекламируется."""
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
        return device

    async def _attach(self, device: BLEDevice) -> None:
        """Подключиться к найденному устройству и подписаться на нотификации."""
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
        """Сопряжение: BlueZ ``Device1.Pair()`` строго до GATT-операций (спека §1.7).

        S4 в режиме сопряжения принимает LL-соединение, но рвёт его, если
        центральный начинает GATT-discovery раньше SMP, поэтому пейринг идёт
        отдельным примитивом BlueZ на объекте устройства. Метод самодостаточен:
        на время пейринга регистрирует JustWorks-агент и включает ``Pairable``
        на адаптере (без них bluetoothd отвечает ``AuthenticationFailed``),
        после — возвращает адаптер в исходное состояние. Успешный пейринг
        оставляет транспорт подключённым и готовым к работе.
        """
        self._queue = asyncio.Queue()
        device = await self._find_device()
        details = device.details
        path = details.get("path") if isinstance(details, dict) else None
        if not isinstance(path, str):
            raise TransportError(
                f"сопряжение с {self._address}: поддерживается только BlueZ"
            )
        adapter_path = path.rsplit("/", 1)[0]
        try:
            bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        except OSError as exc:
            raise TransportError(f"сопряжение с {self._address}: D-Bus: {exc}") from exc
        agent = JustWorksAgent()
        was_pairable = True
        try:
            was_pairable = await self._enable_pairable(bus, adapter_path)
            await self._register_agent(bus, agent)
            try:
                async with asyncio.timeout(45.0):
                    reply = await bus.call(
                        Message(
                            destination="org.bluez",
                            path=path,
                            interface="org.bluez.Device1",
                            member="Pair",
                        )
                    )
            except (TimeoutError, OSError) as exc:
                raise TransportError(f"сопряжение с {self._address}: {exc}") from exc
            if (
                reply is not None
                and reply.message_type is MessageType.ERROR
                and reply.error_name != _BLUEZ_ALREADY_EXISTS
            ):
                raise TransportError(
                    f"сопряжение с {self._address}: {reply.error_name}: {reply.body}"
                )
        finally:
            await self._restore_adapter(bus, adapter_path, agent, was_pairable)
            bus.disconnect()
        log.debug("paired", address=self._address)
        await self._attach(device)

    @staticmethod
    async def _adapter_call(
        bus: MessageBus,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: list[object] | None = None,
    ) -> Message | None:
        """Вызов метода BlueZ; ошибки транслируются вызывающему кодом ответа."""
        return await bus.call(
            Message(
                destination="org.bluez",
                path=path,
                interface=interface,
                member=member,
                signature=signature,
                body=body or [],
            )
        )

    async def _enable_pairable(self, bus: MessageBus, adapter_path: str) -> bool:
        """Включает ``Pairable`` на адаптере; возвращает прежнее значение."""
        reply = await self._adapter_call(
            bus,
            adapter_path,
            "org.freedesktop.DBus.Properties",
            "Get",
            "ss",
            ["org.bluez.Adapter1", "Pairable"],
        )
        was_pairable = bool(
            reply is not None
            and reply.message_type is not MessageType.ERROR
            and reply.body[0].value
        )
        if not was_pairable:
            await self._adapter_call(
                bus,
                adapter_path,
                "org.freedesktop.DBus.Properties",
                "Set",
                "ssv",
                ["org.bluez.Adapter1", "Pairable", Variant("b", True)],
            )
            log.debug("adapter_pairable_enabled", adapter=adapter_path)
        return was_pairable

    async def _register_agent(self, bus: MessageBus, agent: JustWorksAgent) -> None:
        """Экспортирует и регистрирует JustWorks-агент (default — по возможности)."""
        bus.export(AGENT_PATH, agent)
        reply = await self._adapter_call(
            bus,
            "/org/bluez",
            "org.bluez.AgentManager1",
            "RegisterAgent",
            "os",
            [AGENT_PATH, AGENT_CAPABILITY],
        )
        if (
            reply is not None
            and reply.message_type is MessageType.ERROR
            and reply.error_name != _BLUEZ_ALREADY_EXISTS
        ):
            raise TransportError(f"регистрация BlueZ-агента: {reply.error_name}")
        default = await self._adapter_call(
            bus,
            "/org/bluez",
            "org.bluez.AgentManager1",
            "RequestDefaultAgent",
            "o",
            [AGENT_PATH],
        )
        if default is not None and default.message_type is MessageType.ERROR:
            # не фатально: для исходящего JustWorks хватает зарегистрированного
            log.debug("agent_default_refused", error=default.error_name)

    async def _restore_adapter(
        self,
        bus: MessageBus,
        adapter_path: str,
        agent: JustWorksAgent,
        was_pairable: bool,
    ) -> None:
        """Снимает агент и возвращает ``Pairable`` как было; сбои — в DEBUG-лог."""
        try:
            reply = await self._adapter_call(
                bus,
                "/org/bluez",
                "org.bluez.AgentManager1",
                "UnregisterAgent",
                "o",
                [AGENT_PATH],
            )
            if reply is not None and reply.message_type is MessageType.ERROR:
                log.debug("agent_unregister_failed", error=reply.error_name)
            bus.unexport(AGENT_PATH, agent)
            if not was_pairable:
                await self._adapter_call(
                    bus,
                    adapter_path,
                    "org.freedesktop.DBus.Properties",
                    "Set",
                    "ssv",
                    ["org.bluez.Adapter1", "Pairable", Variant("b", False)],
                )
                log.debug("adapter_pairable_restored", adapter=adapter_path)
        except OSError as exc:
            log.debug("adapter_restore_failed", error=str(exc))

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
