"""Датчики: ingest, телеметрия, MagicAir-опрос, MQTT-разбор (Фаза 6)."""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import httpx
from sqlalchemy import select

from easy_breezy.core.events import (
    TOPIC_DEVICE_LIST_CHANGED,
    TOPIC_SENSOR_UPDATED,
    EventBus,
)
from easy_breezy.core.sensors import KIND_MQTT, SensorIngest, clean_metrics
from easy_breezy.core.telemetry import TelemetryService
from easy_breezy.integrations.magicair.client import (
    LOCATION_URL,
    TOKEN_URL,
    MagicAirPoller,
)
from easy_breezy.integrations.mqtt.client import MqttIngest, parse_payload
from easy_breezy.storage import Database
from easy_breezy.storage.models import TelemetryRaw
from easy_breezy.storage.repos import SensorRepo
from tests.conftest import CoreEnv


def test_clean_metrics_filters_garbage() -> None:
    raw: dict[str, Any] = {
        "co2": 850,
        "temperature": 23.5,
        "humidity": float("nan"),
        "pm25": 12.0,  # неизвестная метрика
        "co2_extra": True,
    }
    assert clean_metrics(raw) == {"co2": 850.0, "temperature": 23.5}
    assert clean_metrics({"co2": "800"}) == {}  # строки не приводим
    assert clean_metrics({"co2": True}) == {}  # bool — не число
    assert clean_metrics({"humidity": math.inf}) == {}


async def test_ingest_auto_register_and_events(db: Database) -> None:
    events = EventBus()
    ingest = SensorIngest(db, events)
    with events.subscribe(TOPIC_SENSOR_UPDATED, TOPIC_DEVICE_LIST_CHANGED) as sub:
        sensor_id = await ingest.ingest(
            kind="magicair",
            source_key="magicair:guid-1",
            name="Гостиная CO2+",
            metrics={"co2": 900, "temperature": 24, "pm25": float("nan")},
            auto_register=True,
        )
        assert sensor_id is not None
        first = await asyncio.wait_for(sub.get(), 1)
        second = await asyncio.wait_for(sub.get(), 1)
    topics = {first.topic, second.topic}
    assert topics == {TOPIC_SENSOR_UPDATED, TOPIC_DEVICE_LIST_CHANGED}

    async with db.session() as session:
        sensor = await SensorRepo(session).get(sensor_id)
        assert sensor is not None
        assert sensor.name == "Гостиная CO2+"
        assert sensor.last_values == {"co2": 900.0, "temperature": 24.0}
        assert sensor.last_seen_at is not None

    # повторный ingest не создаёт дубликат и не трогает имя (владелец мог переименовать)
    again = await ingest.ingest(
        kind="magicair",
        source_key="magicair:guid-1",
        name="Другое имя",
        metrics={"co2": 950},
        auto_register=True,
    )
    assert again == sensor_id
    async with db.session() as session:
        sensors = await SensorRepo(session).list_all()
    assert len(sensors) == 1
    assert sensors[0].name == "Гостиная CO2+"
    # свежий co2 поверх прежнего среза, температура сохранилась
    assert sensors[0].last_values == {"co2": 950.0, "temperature": 24.0}


async def test_ingest_unknown_mqtt_source_ignored(db: Database) -> None:
    events = EventBus()
    ingest = SensorIngest(db, events)
    result = await ingest.ingest(
        kind=KIND_MQTT, source_key="home/unknown", metrics={"co2": 700}
    )
    assert result is None
    async with db.session() as session:
        assert await SensorRepo(session).list_all() == []


async def test_sensor_telemetry_recorded(db: Database) -> None:
    """sensor.updated пишется рекордером в telemetry_raw (FR-28)."""
    events = EventBus()
    telemetry = TelemetryService(db, events)
    await telemetry.start()
    try:
        ingest = SensorIngest(db, events)
        sensor_id = await ingest.ingest(
            kind="magicair",
            source_key="magicair:guid-t",
            metrics={"co2": 1200, "humidity": 40},
            auto_register=True,
        )

        async def points() -> list[tuple[str, float]]:
            async with db.session() as session:
                result = await session.execute(
                    select(TelemetryRaw.metric, TelemetryRaw.value).where(
                        TelemetryRaw.source_type == "sensor",
                        TelemetryRaw.source_id == str(sensor_id),
                    )
                )
                return [(metric, value) for metric, value in result.all()]

        for _ in range(100):
            if len(await points()) == 2:
                break
            await asyncio.sleep(0.01)
        assert dict(await points()) == {"co2": 1200.0, "humidity": 40.0}
    finally:
        await telemetry.stop()


# --- MagicAir ----------------------------------------------------------------


def magicair_transport(
    calls: list[str], *, fail_first_location: bool = False
) -> httpx.MockTransport:
    location_payload = [
        {
            "name": "Дом",
            "zones": [
                {
                    "name": "Гостиная",
                    "devices": [
                        {
                            "guid": "guid-co2",
                            "type": "co2th",
                            "name": "MagicAir",
                            "data": {
                                "co2": 950,
                                "temperature": 24.5,
                                "humidity": 38,
                                "pm25": float("nan"),
                            },
                        },
                        {"guid": "guid-br", "type": "breezer4", "data": {}},
                    ],
                },
                "мусорная запись",
            ],
        }
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url}")
        if str(request.url) == TOKEN_URL:
            body = request.content.decode()
            assert "grant_type=password" in body
            assert "client_id=" in body
            return httpx.Response(
                200, json={"access_token": "tok-1", "expires_in": 3600}
            )
        if str(request.url) == LOCATION_URL:
            if request.headers.get("Authorization") != "Bearer tok-1":
                return httpx.Response(401)
            if fail_first_location and calls.count(f"GET {LOCATION_URL}") == 1:
                return httpx.Response(401)
            return httpx.Response(
                200,
                content=json.dumps(location_payload),
                headers={"Content-Type": "application/json"},
            )
        return httpx.Response(404)

    return httpx.MockTransport(handler)


async def test_magicair_poll_ingests_co2_devices(db: Database) -> None:
    events = EventBus()
    calls: list[str] = []
    client = httpx.AsyncClient(transport=magicair_transport(calls))
    poller = MagicAirPoller(
        SensorIngest(db, events),
        email="user@example.com",
        password="secret",
        client=client,
    )
    ingested = await poller.poll_once()
    assert ingested == 1  # co2th принят, breezer4 и мусор пропущены

    async with db.session() as session:
        sensors = await SensorRepo(session).list_all()
    assert len(sensors) == 1
    assert sensors[0].source_key == "magicair:guid-co2"
    assert sensors[0].kind == "magicair"
    assert sensors[0].last_values == {
        "co2": 950.0,
        "temperature": 24.5,
        "humidity": 38.0,
    }

    # второй опрос переиспользует токен (не логинится заново)
    await poller.poll_once()
    token_calls = [call for call in calls if call.startswith("POST")]
    assert len(token_calls) == 1
    await client.aclose()


async def test_magicair_disabled_without_credentials(db: Database) -> None:
    poller = MagicAirPoller(SensorIngest(db, EventBus()), email=None, password=None)
    assert not poller.enabled
    await poller.start()  # не падает и ничего не запускает
    await poller.stop()


# --- MQTT --------------------------------------------------------------------


def test_parse_payload_table() -> None:
    # базовый топик: JSON с известными метриками
    assert parse_payload(None, b'{"co2": 800, "temperature": 22, "x": 1}') == {
        "co2": 800,
        "temperature": 22,
    }
    # базовый топик: голое число — CO₂ по умолчанию
    assert parse_payload(None, b"645") == {"co2": 645.0}
    assert parse_payload(None, b" 645.5 ") == {"co2": 645.5}
    # суффикс-топик: число конкретной метрики
    assert parse_payload("temperature", b"21.5") == {"temperature": 21.5}
    assert parse_payload("humidity", b"44") == {"humidity": 44.0}
    # мусор
    assert parse_payload(None, b"not json") == {}
    assert parse_payload("co2", b"abc") == {}
    assert parse_payload("pm25", b"10") == {}  # неизвестная метрика
    assert parse_payload(None, b"true") == {}  # bool — не измерение


async def test_mqtt_handle_routes_by_topic(core: CoreEnv) -> None:
    """Сообщения известных топиков принимаются, чужие игнорируются."""
    ingest = SensorIngest(core.db, core.events)
    async with core.db.session() as session:
        await SensorRepo(session).create(
            kind=KIND_MQTT, name="Спальня CO₂", source_key="home/bedroom/air"
        )
    mqtt = MqttIngest(core.db, ingest, core.events, url="mqtt://localhost")
    base_topics = {"home/bedroom/air"}

    await mqtt._handle("home/bedroom/air", b'{"co2": 777}', base_topics)
    await mqtt._handle("home/bedroom/air/temperature", b"23.5", base_topics)
    await mqtt._handle("home/other", b"999", base_topics)  # чужой — игнор

    async with core.db.session() as session:
        sensor = await SensorRepo(session).get_by_source_key("home/bedroom/air")
        assert sensor is not None
        # метрики из раздельных топиков мержатся в полный срез
        assert sensor.last_values == {"co2": 777.0, "temperature": 23.5}


async def test_mqtt_disabled_without_url(core: CoreEnv) -> None:
    mqtt = MqttIngest(
        core.db, SensorIngest(core.db, core.events), core.events, url=None
    )
    assert not mqtt.enabled
    await mqtt.start()
    await mqtt.stop()
