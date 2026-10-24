"""Адаптер qingping-ble: только CGDN1 и значения текущего BLE-пакета."""

from __future__ import annotations

import re
from dataclasses import dataclass

from home_assistant_bluetooth import BluetoothServiceInfo
from qingping_ble import QingpingBluetoothDeviceData

from easy_breezy.core.sensors import in_range

SERVICE_UUID = "0000fdcd-0000-1000-8000-00805f9b34fb"
SOURCE_PREFIX = "qingping_ble:"
_METRICS = {
    "temperature": "temperature",
    "humidity": "humidity",
    "carbon_dioxide": "co2",
    "pm25": "pm25",
    "pm10": "pm10",
    "battery": "battery",
}


def normalize_mac(value: str) -> str:
    """MAC в любом написании (с ``:``/``-`` или без) → ``AA:BB:CC:DD:EE:FF``."""
    mac = re.sub(r"[:\-\s]", "", value).upper()
    if not re.fullmatch(r"[0-9A-F]{12}", mac) or mac in {"0" * 12, "F" * 12}:
        raise ValueError("укажите MAC Qingping: AA:BB:CC:DD:EE:FF")
    return ":".join(mac[i : i + 2] for i in range(0, 12, 2))


def source_key(value: str) -> str:
    """Нормализует MAC из пакета/ручного ввода в отдельное пространство ключей."""
    return SOURCE_PREFIX + normalize_mac(value.removeprefix(SOURCE_PREFIX))


@dataclass(frozen=True)
class Reading:
    source_key: str
    metrics: dict[str, float]


def parse_advertisement(data: bytes, *, rssi: int = 0) -> Reading | None:
    """Разбирает FDCD service data; повреждённые/чужие пакеты игнорируются.

    Идентификатор берётся из payload: эфирный адрес может меняться.
    Новый экземпляр парсера на пакет исключает перенос его кэша CO₂.
    """
    if len(data) < 10 or data[1] not in (0x0E, 0x24):
        return None
    offset = 8
    while offset < len(data):
        if offset + 2 > len(data):
            return None
        kind, size = data[offset : offset + 2]
        if size != {0x01: 4, 0x13: 2}.get(kind, size):
            return None
        offset += 2 + size
        if offset > len(data):
            return None
    try:
        key = source_key(data[2:8][::-1].hex())
    except ValueError:
        return None
    info = BluetoothServiceInfo(
        name="Qingping Air Monitor Lite",
        address=key.removeprefix(SOURCE_PREFIX),
        rssi=rssi,
        manufacturer_data={},
        service_data={SERVICE_UUID: data},
        service_uuids=[SERVICE_UUID],
        source="local",
    )
    update = QingpingBluetoothDeviceData().update(info)
    metrics: dict[str, float] = {}
    for device_key, sensor in update.entity_values.items():
        if device_key.key not in _METRICS:
            continue
        metric = _METRICS[device_key.key]
        value = sensor.native_value
        if isinstance(value, (int, float)) and in_range(metric, value):
            metrics[metric] = float(value)
    return Reading(key, metrics) if metrics else None
