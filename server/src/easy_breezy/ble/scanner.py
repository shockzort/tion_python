"""Поиск бризеров Tion в эфире (фильтр по имени, сортировка по RSSI)."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass

import structlog
from bleak import BleakScanner
from bleak.exc import BleakError

from easy_breezy.ble.transport import TransportError

log = structlog.get_logger("easy_breezy.ble")

# Полевой факт (смоук Фазы 1): S4 рекламируется как 'Breezer 4S', без «Tion»
_NAME_PREFIXES = ("breezer", "tion breezer", "tion_", "tion ")
_MODEL_HINTS = {"4s": "s4", "s4": "s4", "lite": "lite", "3s": "s3", "s3": "s3"}

_TION_MFR_COMPANY = 0xFFFF
_MFR_PAYLOAD_LEN = 11  # <mac:6> 03 80 00 00 <pair:1> — спека §1.1


def pairing_mode_from_adv(manufacturer_data: dict[int, bytes]) -> bool | None:
    """Флаг режима сопряжения из рекламы (спека §1.1); None — неизвестно."""
    payload = manufacturer_data.get(_TION_MFR_COMPANY)
    if payload is None or len(payload) < _MFR_PAYLOAD_LEN:
        return None
    return payload[_MFR_PAYLOAD_LEN - 1] == 1


@dataclass(frozen=True, slots=True)
class DiscoveredBreezer:
    name: str
    address: str
    rssi: int
    model_hint: str | None
    pairing_mode: bool | None = None
    """True — бризер в режиме сопряжения (кнопка ~5 с / выкл-вкл)."""


def _match(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.startswith(prefix) for prefix in _NAME_PREFIXES)


def _model_hint(name: str) -> str | None:
    lowered = name.lower()
    for marker, model in _MODEL_HINTS.items():
        if marker in lowered:
            return model
    return None


async def scan(
    duration: float = 15.0, *, gate: asyncio.Lock | None = None
) -> list[DiscoveredBreezer]:
    """Активный скан эфира.

    ``gate`` — общий лок со супервизорами: скан и попытки подключения
    взаимоисключены (борьба за BLE-адаптер, план §7).
    """
    async with AsyncExitStack() as stack:
        if gate is not None:
            await stack.enter_async_context(gate)
        try:
            results = await BleakScanner.discover(timeout=duration, return_adv=True)
        except (BleakError, OSError) as exc:
            raise TransportError(f"скан не удался: {exc}") from exc

    found = [
        DiscoveredBreezer(
            name=name,
            address=device.address,
            rssi=adv.rssi,
            model_hint=_model_hint(name),
            pairing_mode=pairing_mode_from_adv(adv.manufacturer_data),
        )
        for device, adv in results.values()
        if (name := device.name or adv.local_name or "") and _match(name)
    ]
    found.sort(key=lambda item: item.rssi, reverse=True)
    log.info("scan_finished", duration=duration, found=len(found))
    return found
