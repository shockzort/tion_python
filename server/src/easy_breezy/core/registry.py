"""Реестр устройств: супервизор на каждое сопряжённое устройство (план §3, §7).

Единственное место, где BLE-колбэки превращаются в записи кэша и события
шины; интеграции подписываются на события и не знают про BLE.
"""

from __future__ import annotations

import asyncio
import functools
import time
from collections.abc import Callable

import structlog

from easy_breezy.ble.protocol.s4 import S4State
from easy_breezy.ble.supervisor import ConnectionState, DeviceSupervisor
from easy_breezy.ble.transport import BleTransport
from easy_breezy.core.events import (
    TOPIC_CONNECTION_CHANGED,
    TOPIC_DEVICE_LIST_CHANGED,
    TOPIC_STATE_CHANGED,
    EventBus,
)
from easy_breezy.core.model import state_to_dict
from easy_breezy.core.state import StateCache
from easy_breezy.storage import Database
from easy_breezy.storage.models import Device
from easy_breezy.storage.repos import DeviceRepo

log = structlog.get_logger(__name__)


class DeviceRegistry:
    """Жизненный цикл супервизоров поверх таблицы devices.

    ``transport_factory`` по MAC создаёт свежий транспорт (вызывается
    супервизором на каждую попытку подключения). Параметры супервизора
    вынесены в конструктор — тесты задают быстрые значения.
    """

    def __init__(
        self,
        db: Database,
        events: EventBus,
        cache: StateCache,
        transport_factory: Callable[[str], BleTransport],
        *,
        now: Callable[[], float] = time.time,
        scan_gate: asyncio.Lock | None = None,
        poll_interval: float = 30.0,
        backoff_initial: float = 1.0,
        backoff_max: float = 60.0,
        response_timeout: float = 3.0,
    ) -> None:
        self._db = db
        self._events = events
        self._cache = cache
        self._transport_factory = transport_factory
        self._now = now
        self._scan_gate = scan_gate
        self._poll_interval = poll_interval
        self._backoff_initial = backoff_initial
        self._backoff_max = backoff_max
        self._response_timeout = response_timeout
        self._supervisors: dict[str, DeviceSupervisor] = {}

    async def start(self) -> None:
        """Поднимает супервизоры для всех активных сопряжённых устройств."""
        async with self._db.session() as session:
            devices = await DeviceRepo(session).list_active()
        for device in devices:
            if device.paired:
                self._start_supervisor(device.uuid, device.mac)
        log.info("registry_started", devices=len(self._supervisors))

    async def stop(self) -> None:
        supervisors = list(self._supervisors.values())
        self._supervisors.clear()
        await asyncio.gather(*(supervisor.stop() for supervisor in supervisors))
        log.info("registry_stopped")

    def supervisor(self, device_uuid: str) -> DeviceSupervisor | None:
        return self._supervisors.get(device_uuid)

    def connection(self, device_uuid: str) -> ConnectionState:
        supervisor = self._supervisors.get(device_uuid)
        if supervisor is None:
            return ConnectionState.DISCONNECTED
        return supervisor.connection_state

    async def add_device(self, *, mac: str, name: str, paired: bool = True) -> Device:
        """Регистрирует устройство и запускает супервизор.

        Фаза 2: устройство считается уже сопряжённым на хосте
        (``breezy pair``); мастер сопряжения из UI — Фаза 3.
        """
        async with self._db.session() as session:
            device = await DeviceRepo(session).create(
                mac=mac,
                name=name,
                paired=paired,
                created_at=int(self._now()),
            )
        if paired:
            self._start_supervisor(device.uuid, device.mac)
        self._events.publish(
            TOPIC_DEVICE_LIST_CHANGED,
            {"action": "added", "device_uuid": device.uuid},
        )
        return device

    async def remove_device(self, device_uuid: str) -> bool:
        """Останавливает супервизор и мягко удаляет устройство."""
        supervisor = self._supervisors.pop(device_uuid, None)
        if supervisor is not None:
            await supervisor.stop()
        async with self._db.session() as session:
            repo = DeviceRepo(session)
            device = await repo.get(device_uuid)
            if device is None or device.deleted_at is not None:
                return False
            await repo.soft_delete(device, deleted_at=int(self._now()))
        self._cache.remove(device_uuid)
        self._events.publish(
            TOPIC_DEVICE_LIST_CHANGED,
            {"action": "removed", "device_uuid": device_uuid},
        )
        return True

    def _start_supervisor(self, device_uuid: str, mac: str) -> None:
        self._cache.ensure(device_uuid)
        supervisor = DeviceSupervisor(
            functools.partial(self._transport_factory, mac),
            poll_interval=self._poll_interval,
            backoff_initial=self._backoff_initial,
            backoff_max=self._backoff_max,
            response_timeout=self._response_timeout,
            scan_gate=self._scan_gate,
            on_state=functools.partial(self._handle_state, device_uuid),
            on_connection=functools.partial(self._handle_connection, device_uuid),
        )
        self._supervisors[device_uuid] = supervisor
        supervisor.start()

    def _handle_state(self, device_uuid: str, state: S4State) -> None:
        self._cache.update_state(device_uuid, state)
        self._events.publish(
            TOPIC_STATE_CHANGED,
            {"device_uuid": device_uuid, "state": state_to_dict(state)},
        )

    def _handle_connection(self, device_uuid: str, connection: ConnectionState) -> None:
        self._cache.update_connection(device_uuid, connection)
        self._events.publish(
            TOPIC_CONNECTION_CHANGED,
            {"device_uuid": device_uuid, "connection": connection.value},
        )
