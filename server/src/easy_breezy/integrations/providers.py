"""Реестр провайдеров датчиков: что умеет каждый источник показаний.

UI строит мастер «тип → поиск → выбор → имя и комната» по этому описанию,
не зная конкретных моделей. Новый источник = новая запись здесь
(+ ``SensorDiscovery``, если он умеет искать).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from easy_breezy.core.sensors import (
    CLIMATE_METRICS,
    KIND_MAGICAIR,
    KIND_MQTT,
    KIND_QINGPING_BLE,
    KIND_QINGPING_MQTT,
)
from easy_breezy.integrations.qingping import mqtt as qingping_mqtt
from easy_breezy.integrations.qingping import parser as qingping_ble

QINGPING_METRICS = ("co2", "temperature", "humidity", "pm25", "pm10", "battery")


def _mqtt_topic(value: str) -> str:
    topic = value.strip().strip("/")
    if not topic or any(char in topic for char in "+#"):
        raise ValueError("укажите базовый MQTT-топик без масок (home/bedroom/air)")
    if topic.startswith("qingping/"):
        raise ValueError("топики qingping/… принимает провайдер Qingping (Wi-Fi)")
    for prefix in (qingping_ble.SOURCE_PREFIX, qingping_mqtt.SOURCE_PREFIX):
        if topic.startswith(prefix):
            raise ValueError("этот префикс зарезервирован для Qingping")
    return topic


@dataclass(frozen=True)
class SensorProvider:
    """Описание источника показаний для API и UI."""

    kind: str
    title: str
    transport: str
    """cloud | mqtt | ble — для иконки и подсказок."""
    description: str
    metrics: tuple[str, ...]
    """Что датчик этого типа умеет измерять (capabilities)."""
    manual: bool
    """Можно добавить вручную по адресу (иначе — только автоматически)."""
    discoverable: bool
    address_label: str | None = None
    address_placeholder: str | None = None
    normalize: Callable[[str], str] | None = field(default=None, repr=False)
    available: bool = True
    unavailable_reason: str | None = None

    def source_key(self, address: str) -> str:
        """Адрес из UI → ключ реестра; кривой адрес — ``ValueError``."""
        if self.normalize is None:
            raise ValueError("этот тип датчика добавляется автоматически")
        return self.normalize(address.strip())


def build_providers(*, mqtt_enabled: bool, ble_enabled: bool) -> list[SensorProvider]:
    """Провайдеры в порядке показа; недоступные помечены причиной."""
    no_broker = None if mqtt_enabled else "брокер MQTT не настроен (EB_MQTT_URL)"
    return [
        SensorProvider(
            kind=KIND_QINGPING_MQTT,
            title="Qingping Air Monitor Lite · Wi-Fi",
            transport="mqtt",
            description=(
                "Датчик шлёт показания на брокер сервиса по Wi-Fi раз в минуту. "
                "Настройка — один раз на портале Qingping (docs/qingping.md)."
            ),
            metrics=QINGPING_METRICS,
            manual=True,
            discoverable=True,
            address_label="MAC Wi-Fi",
            address_placeholder="EC4D3E7DB360",
            normalize=qingping_mqtt.source_key,
            available=mqtt_enabled,
            unavailable_reason=no_broker,
        ),
        SensorProvider(
            kind=KIND_QINGPING_BLE,
            title="Qingping Air Monitor Lite · Bluetooth",
            transport="ble",
            description=(
                "Пассивный приём BLE-рекламы. Датчик должен быть в радиусе "
                "Bluetooth сервера; сканирование уступает эфир бризерам."
            ),
            metrics=QINGPING_METRICS,
            manual=True,
            discoverable=True,
            address_label="MAC Bluetooth",
            address_placeholder="AA:BB:CC:DD:EE:FF",
            normalize=qingping_ble.source_key,
            available=ble_enabled,
            unavailable_reason=None if ble_enabled else "Bluetooth выключен",
        ),
        SensorProvider(
            kind=KIND_MQTT,
            title="MQTT-датчик",
            transport="mqtt",
            description=(
                "Любой датчик, публикующий JSON {co2, temperature, …} или числа "
                "в топики вида <база>/co2."
            ),
            metrics=CLIMATE_METRICS,
            manual=True,
            discoverable=False,
            address_label="Базовый топик",
            address_placeholder="home/bedroom/air",
            normalize=_mqtt_topic,
            available=mqtt_enabled,
            unavailable_reason=no_broker,
        ),
        SensorProvider(
            kind=KIND_MAGICAIR,
            title="Tion MagicAir",
            transport="cloud",
            description="Датчики облака MagicAir появляются сами (учётка в .env).",
            metrics=CLIMATE_METRICS,
            manual=False,
            discoverable=False,
        ),
    ]
