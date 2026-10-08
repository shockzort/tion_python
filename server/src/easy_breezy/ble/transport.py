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
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
from dbus_fast import BusType, Message, MessageType, Variant
from dbus_fast.aio import MessageBus

from easy_breezy.ble._bluez_agent import AGENT_CAPABILITY, AGENT_PATH, JustWorksAgent
from easy_breezy.ble.discovery import scanning

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
        self._ready = False
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
        сначала ограниченный по времени поиск, затем connect по BLEDevice.
        """
        self._queue = asyncio.Queue()
        device = await self._find_device()
        await self._attach(device)

    async def _find_device(self) -> BLEDevice:
        """Найти устройство в эфире; занятый другим центральным не рекламируется."""
        found = asyncio.Event()
        device: BLEDevice | None = None

        def on_advertisement(candidate: BLEDevice, _adv: AdvertisementData) -> None:
            nonlocal device
            if candidate.address.upper() == self._address.upper():
                device = candidate
                found.set()

        started = asyncio.get_running_loop().time()
        try:
            async with scanning(BleakScanner(detection_callback=on_advertisement)):
                async with asyncio.timeout(14.0):
                    await found.wait()
        except (BleakError, TimeoutError, OSError) as exc:
            log.warning(
                "device_search_failed",
                address=self._address,
                elapsed_s=round(asyncio.get_running_loop().time() - started, 2),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise TransportError(f"поиск {self._address} в эфире: {exc}") from exc
        if device is None:
            raise TransportError(f"{self._address} не найден в эфире")
        log.info(
            "device_found",
            address=self._address,
            elapsed_s=round(asyncio.get_running_loop().time() - started, 2),
        )
        return device

    async def _attach(self, device: BLEDevice) -> None:
        """Подключиться к найденному устройству и подписаться на нотификации."""
        self._client = BleakClient(
            device,
            disconnected_callback=self._on_disconnect,
            timeout=self._connect_timeout,
        )
        stage = "connect"
        attached = False
        started = asyncio.get_running_loop().time()
        try:
            async with asyncio.timeout(self._connect_timeout + 10):
                await self._client.connect()
            stage = "start_notify"
            async with asyncio.timeout(self._operation_timeout * 2):
                await self._client.start_notify(self._notify_uuid, self._on_notify)
            if not self._client.is_connected:
                raise TransportError("соединение потеряно во время start_notify")
            self._ready = True
            attached = True
        except (BleakError, TimeoutError, OSError) as exc:
            log.warning(
                "transport_start_failed",
                address=self._address,
                stage=stage,
                elapsed_s=round(asyncio.get_running_loop().time() - started, 2),
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise TransportError(f"{stage} {self._address}: {exc}") from exc
        finally:
            if not attached:
                await self.disconnect()
        log.info(
            "transport_connected",
            address=self._address,
            elapsed_s=round(asyncio.get_running_loop().time() - started, 2),
        )

    async def disconnect(self) -> None:
        self._ready = False
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
            self._client = None
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
        bus = MessageBus(bus_type=BusType.SYSTEM)
        agent = JustWorksAgent()
        was_pairable: bool | None = None
        pair_started = False
        paired = False
        try:
            async with asyncio.timeout(self._operation_timeout):
                await bus.connect()
            was_pairable = await self._get_pairable(bus, adapter_path)
            if not was_pairable:
                await self._set_pairable(bus, adapter_path, True)
            await self._register_agent(bus, agent)
            pair_started = True
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
            paired = True
        except (TimeoutError, OSError) as exc:
            raise TransportError(f"сопряжение с {self._address}: D-Bus: {exc}") from exc
        finally:
            try:
                if pair_started and not paired:
                    for member in ("CancelPairing", "Disconnect"):
                        try:
                            await self._adapter_call(
                                bus, path, "org.bluez.Device1", member
                            )
                        except TransportError as exc:
                            log.warning(
                                "pair_cleanup_failed",
                                address=self._address,
                                stage=member,
                                error=str(exc),
                            )
                if was_pairable is not None:
                    await self._restore_adapter(bus, adapter_path, agent, was_pairable)
            finally:
                bus.disconnect()
        log.debug("paired", address=self._address)
        await self._attach(device)

    async def _adapter_call(
        self,
        bus: MessageBus,
        path: str,
        interface: str,
        member: str,
        signature: str = "",
        body: list[object] | None = None,
    ) -> Message | None:
        """Вызов метода BlueZ; ошибки транслируются вызывающему кодом ответа."""
        try:
            async with asyncio.timeout(self._operation_timeout):
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
        except (TimeoutError, OSError) as exc:
            raise TransportError(
                f"BlueZ {member}: {type(exc).__name__}: {exc}"
            ) from exc

    async def _get_pairable(self, bus: MessageBus, adapter_path: str) -> bool:
        """Читает исходное значение; неизвестное состояние не заменяется False."""
        reply = await self._adapter_call(
            bus,
            adapter_path,
            "org.freedesktop.DBus.Properties",
            "Get",
            "ss",
            ["org.bluez.Adapter1", "Pairable"],
        )
        if reply is None or reply.message_type is MessageType.ERROR:
            raise TransportError("не удалось прочитать Pairable адаптера")
        return bool(reply.body[0].value)

    async def _set_pairable(
        self, bus: MessageBus, adapter_path: str, value: bool
    ) -> None:
        reply = await self._adapter_call(
            bus,
            adapter_path,
            "org.freedesktop.DBus.Properties",
            "Set",
            "ssv",
            ["org.bluez.Adapter1", "Pairable", Variant("b", value)],
        )
        if reply is None or reply.message_type is MessageType.ERROR:
            raise TransportError("не удалось установить Pairable адаптера")

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
        was_pairable: bool | None,
    ) -> None:
        """Независимо снимает агент и возвращает известное исходное Pairable."""
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
        except TransportError as exc:
            log.warning("agent_unregister_failed", error=str(exc))
        finally:
            bus.unexport(AGENT_PATH, agent)
        if was_pairable is False:
            try:
                await self._set_pairable(bus, adapter_path, False)
            except TransportError as exc:
                log.warning("adapter_restore_failed", error=str(exc))

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
        log.info("ble_disconnected", address=self._address, session_ready=self._ready)
        # Bleak повторяет неудачные соединения внутри connect(). Эти callbacks
        # не должны завершать поток нотификаций будущей успешной сессии.
        if self._ready:
            self._ready = False
            self._queue.put_nowait(None)
