"""Кэш последнего подтверждённого состояния устройств.

Запросные пути (REST, Яндекс /query) читают только отсюда — live-BLE в
запросном пути запрещён (план §6). Пишут кэш колбэки реестра.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, replace

from easy_breezy.ble.protocol.s4 import S4State
from easy_breezy.ble.supervisor import ConnectionState


@dataclass(frozen=True, slots=True)
class DeviceSnapshot:
    """Последнее известное состояние одного устройства."""

    state: S4State | None = None
    connection: ConnectionState = ConnectionState.DISCONNECTED
    state_at: float | None = None
    """Unix-время последнего кадра состояния."""
    connection_at: float | None = None
    """Unix-время последней смены состояния соединения."""


class StateCache:
    def __init__(self, *, now: Callable[[], float] = time.time) -> None:
        self._now = now
        self._snapshots: dict[str, DeviceSnapshot] = {}

    def ensure(self, device_uuid: str) -> None:
        """Регистрирует устройство с пустым снапшотом (при старте реестра)."""
        self._snapshots.setdefault(device_uuid, DeviceSnapshot())

    def update_state(self, device_uuid: str, state: S4State) -> None:
        snapshot = self._snapshots.get(device_uuid, DeviceSnapshot())
        self._snapshots[device_uuid] = replace(
            snapshot, state=state, state_at=self._now()
        )

    def update_connection(self, device_uuid: str, connection: ConnectionState) -> None:
        snapshot = self._snapshots.get(device_uuid, DeviceSnapshot())
        self._snapshots[device_uuid] = replace(
            snapshot, connection=connection, connection_at=self._now()
        )

    def get(self, device_uuid: str) -> DeviceSnapshot | None:
        return self._snapshots.get(device_uuid)

    def remove(self, device_uuid: str) -> None:
        self._snapshots.pop(device_uuid, None)
