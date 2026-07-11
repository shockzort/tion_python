"""Мастер сопряжения: скан эфира и создание бонда (план §7, ADR-0003).

Реальная реализация сканирует через общий scan-gate (скан ⊕ connect) и
сопрягает самодостаточным ``transport.pair()``; фейковая — отдаёт пул
«несопряжённых» эмуляторов для разработки UI без железа. Прогресс пейринга
публикуется в шину (``pairing.progress``) — мастер показывает стадии по WS.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import structlog

from easy_breezy.ble import scanner
from easy_breezy.ble.fake import fake_mac
from easy_breezy.ble.transport import BleTransport, TransportError
from easy_breezy.core.events import TOPIC_PAIRING_PROGRESS, EventBus
from easy_breezy.core.registry import DeviceRegistry
from easy_breezy.storage import Database
from easy_breezy.storage.models import Device
from easy_breezy.storage.repos import DeviceRepo

log = structlog.get_logger(__name__)


class PairingError(Exception):
    """Сопряжение не удалось (бризер не в режиме сопряжения, эфир, бонд)."""


@dataclass(frozen=True, slots=True)
class FoundBreezer:
    mac: str
    name: str
    rssi: int | None
    model_hint: str | None
    pairing_mode: bool | None
    """True — мигает синим (байт рекламы); None — реклама без флага."""
    registered: bool
    """Уже есть в реестре (активная запись devices)."""


class PairingService(Protocol):
    async def scan(self, duration: float = 15.0) -> list[FoundBreezer]: ...

    async def pair(self, mac: str, name: str) -> Device: ...


async def _registered_macs(db: Database) -> set[str]:
    async with db.session() as session:
        devices = await DeviceRepo(session).list_active()
    return {device.mac for device in devices}


class BlePairingService:
    """Сопряжение с настоящим бризером (ADR-0003: SMP до GATT, агент внутри)."""

    def __init__(
        self,
        db: Database,
        registry: DeviceRegistry,
        events: EventBus,
        transport_factory: Callable[[str], BleTransport],
        *,
        scan_gate: asyncio.Lock | None = None,
    ) -> None:
        self._db = db
        self._registry = registry
        self._events = events
        self._transport_factory = transport_factory
        self._scan_gate = scan_gate

    async def scan(self, duration: float = 15.0) -> list[FoundBreezer]:
        found = await scanner.scan(duration, gate=self._scan_gate)
        registered = await _registered_macs(self._db)
        return [
            FoundBreezer(
                mac=item.address.upper(),
                name=item.name,
                rssi=item.rssi,
                model_hint=item.model_hint,
                pairing_mode=item.pairing_mode,
                registered=item.address.upper() in registered,
            )
            for item in found
        ]

    async def pair(self, mac: str, name: str) -> Device:
        self._progress("pairing", mac=mac)
        transport = self._transport_factory(mac)
        try:
            await transport.pair()
        except TransportError as exc:
            self._progress("failed", mac=mac, error=str(exc))
            raise PairingError(str(exc)) from exc
        finally:
            # пейринг поднимает соединение — отпускаем его супервизору
            try:
                await transport.disconnect()
            except TransportError as exc:
                log.debug("pairing_disconnect_failed", mac=mac, error=str(exc))
        self._progress("registering", mac=mac)
        device = await self._registry.add_device(mac=mac, name=name)
        self._progress("done", mac=mac, device_uuid=device.uuid)
        return device

    def _progress(self, stage: str, **data: str) -> None:
        log.info("pairing_progress", stage=stage, **data)
        self._events.publish(TOPIC_PAIRING_PROGRESS, {"stage": stage, **data})


class FakePairingService:
    """Мастер без железа: пул «несопряжённых» фейков за пределами сида."""

    _POOL_SIZE = 2

    def __init__(
        self,
        db: Database,
        registry: DeviceRegistry,
        events: EventBus,
        *,
        seeded: int,
    ) -> None:
        self._db = db
        self._registry = registry
        self._events = events
        self._pool_start = seeded + 1

    async def scan(self, duration: float = 15.0) -> list[FoundBreezer]:
        await asyncio.sleep(min(duration, 1.0))  # UX мастера без долгого ожидания
        registered = await _registered_macs(self._db)
        return [
            FoundBreezer(
                mac=(mac := fake_mac(index)),
                name=f"Breezer 4S (фейк {index})",
                rssi=-40 - index * 5,
                model_hint="s4",
                pairing_mode=True,
                registered=mac in registered,
            )
            for index in range(self._pool_start, self._pool_start + self._POOL_SIZE)
        ]

    async def pair(self, mac: str, name: str) -> Device:
        self._events.publish(TOPIC_PAIRING_PROGRESS, {"stage": "pairing", "mac": mac})
        await asyncio.sleep(0.3)
        self._events.publish(
            TOPIC_PAIRING_PROGRESS, {"stage": "registering", "mac": mac}
        )
        device = await self._registry.add_device(mac=mac, name=name)
        self._events.publish(
            TOPIC_PAIRING_PROGRESS,
            {"stage": "done", "mac": mac, "device_uuid": device.uuid},
        )
        return device
