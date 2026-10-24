"""Qingping по MQTT: разбор протокола, приём, ответы датчику, поиск и API."""

from __future__ import annotations

import json
from typing import Any, cast

import aiomqtt
import pytest

from easy_breezy.core.events import TOPIC_SENSOR_UPDATED, EventBus
from easy_breezy.core.sensors import KIND_QINGPING_MQTT, SensorIngest
from easy_breezy.integrations.qingping.mqtt import (
    NUDGE_AFTER,
    QingpingMqttListener,
    parse_message,
    source_key,
)
from easy_breezy.storage import Database
from easy_breezy.storage.repos import SensorRepo
from tests.conftest import ClientAndApp, FakeClock, bootstrap_admin

TOPIC = "qingping/EC4D3E7DB360/up"
KEY = "qingping_mqtt:EC:4D:3E:7D:B3:60"

# Захват с CGDN1 владельца (прошивка 4.8.5), 2026-10-24.
REALTIME = (
    b'{"type":"12","mac":"EC4D3E7DB360","version":"4.8.5","timezone":30,'
    b'"timestamp":1792850078,"sensorData":[{"timestamp":{"value":1792850078},'
    b'"battery":{"value":100,"status":2},"temperature":{"value":24.84,"status":0,'
    b'"unit":"C","co2_calib_state":0},"humidity":{"value":57.46,"status":0,'
    b'"unit":"%"},"co2":{"value":817,"status":0},"pm25":{"value":8,"status":0},'
    b'"pm10":{"value":8,"status":0}}]}'
)
HEARTBEAT = json.dumps(
    {
        "id": 17,
        "type": "13",
        "wifi_info": "SweetHomeWifi,-36,3,50:FF:20:AC:4F:22",
        "sw_version": "4.8.5",
        "wifi_mac": "EC4D3E7DB360",
        "timestamp": 1792850069,
    }
).encode()


def history(*points: tuple[int, int], message_id: int = 5171) -> bytes:
    return json.dumps(
        {
            "id": message_id,
            "type": "17",
            "mac": "EC4D3E7DB360",
            "need_ack": 1,
            "sensorData": [
                {"co2": {"value": co2}, "timestamp": {"value": ts}}
                for ts, co2 in points
            ],
        }
    ).encode()


class FakeMqtt:
    """Записывает публикации вместо брокера."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: str, payload: bytes, qos: int = 0) -> None:
        self.published.append((topic, json.loads(payload)))

    def types(self) -> list[str]:
        return [body["type"] for _topic, body in self.published]


def test_parse_realtime_capture() -> None:
    message = parse_message(TOPIC, REALTIME)
    assert message is not None
    assert message.source_key == KEY and message.type == "12"
    assert message.metrics == {
        "co2": 817,
        "temperature": 24.84,
        "humidity": 57.46,
        "pm25": 8,
        "pm10": 8,
        "battery": 100,  # status=2 у батареи — питание от USB, не ошибка
    }
    assert message.observed_at == 1792850078


def test_parse_rejects_garbage_and_bad_sensors() -> None:
    assert parse_message("qingping/EC4D3E7DB360/down", REALTIME) is None
    assert parse_message("other/EC4D3E7DB360/up", REALTIME) is None
    assert parse_message("qingping/nope/up", REALTIME) is None
    assert parse_message(TOPIC, b"not json") is None
    assert parse_message(TOPIC, b"[1, 2]") is None
    broken = json.loads(REALTIME)
    entry = broken["sensorData"][0]
    entry["co2"]["status"] = 1  # прогрев/сбой сенсора
    entry["pm25"]["value"] = 99999  # вне физического диапазона
    entry["humidity"]["value"] = True  # bool — не число
    message = parse_message(TOPIC, json.dumps(broken).encode())
    assert message is not None
    assert set(message.metrics) == {"temperature", "pm10", "battery"}
    heartbeat = parse_message(TOPIC, HEARTBEAT)
    assert heartbeat is not None and heartbeat.metrics == {}
    assert heartbeat.signal_dbm == -36 and heartbeat.model_version == "4.8.5"


def test_history_takes_latest_point() -> None:
    message = parse_message(TOPIC, history((1000, 700), (1060, 720), (1030, 710)))
    assert message is not None
    assert message.metrics == {"co2": 720} and message.observed_at == 1060
    assert message.need_ack and message.message_id == 5171


def test_source_key_accepts_any_mac_spelling() -> None:
    assert source_key("ec4d3e7db360") == KEY
    assert source_key("EC:4D:3E:7D:B3:60") == KEY
    assert source_key(KEY) == KEY
    with pytest.raises(ValueError):
        source_key("garbage")


async def make_listener(
    db: Database, clock: FakeClock, *, register: bool
) -> tuple[QingpingMqttListener, FakeMqtt, EventBus]:
    events = EventBus()
    ingest = SensorIngest(db, events, now=clock.now)
    listener = QingpingMqttListener(
        db, ingest, events, url="mqtt://localhost", now=clock.now
    )
    if register:
        async with db.session() as session:
            await SensorRepo(session).create(
                kind=KIND_QINGPING_MQTT, name="Спальня", source_key=KEY
            )
    fake = FakeMqtt()
    listener._client = cast(aiomqtt.Client, fake)
    listener.connected = True
    await listener.reload()
    return listener, fake, events


async def test_unregistered_sensor_is_only_discovered(db: Database) -> None:
    clock = FakeClock(1792850078)
    listener, fake, events = await make_listener(db, clock, register=False)
    with events.subscribe(TOPIC_SENSOR_UPDATED) as sub:
        await listener.handle(TOPIC, REALTIME)
        await listener.handle(TOPIC, HEARTBEAT)
        assert sub._queue.empty()
    found = await listener.discover()
    assert len(found) == 1
    item = found[0]
    assert item.source_key == KEY and item.address == "EC:4D:3E:7D:B3:60"
    assert not item.registered and item.signal_dbm == -36
    # heartbeat не затёр показания, найденные до него
    assert item.metrics["co2"] == 817
    assert fake.published == []  # чужим датчикам реальное время не заказываем


async def test_registered_sensor_ingests_and_requests_realtime(db: Database) -> None:
    clock = FakeClock(1792850078)
    listener, fake, events = await make_listener(db, clock, register=True)
    # регистрация сразу заказывает реальное время
    assert fake.published == [
        (
            "qingping/EC4D3E7DB360/down",
            {"type": "12", "up_itvl": "60", "duration": "3600"},
        )
    ]
    with events.subscribe(TOPIC_SENSOR_UPDATED) as sub:
        await listener.handle(TOPIC, REALTIME)
        event = await sub.get()
    assert event.data["metrics"]["pm25"] == 8
    assert event.data["ts"] == 1792850078
    async with db.session() as session:
        stored = await SensorRepo(session).get_by_source_key(KEY)
        assert stored is not None and stored.last_values is not None
        assert stored.last_values["temperature"] == 24.84
    assert (await listener.discover())[0].registered

    # жив, но показаний нет дольше NUDGE_AFTER — повторный запрос, без спама
    await clock.advance(NUDGE_AFTER + 1)
    await listener.handle(TOPIC, HEARTBEAT)
    await listener.handle(TOPIC, HEARTBEAT)
    assert fake.types() == ["12", "12"]


async def test_bind_request_and_history_ack(db: Database) -> None:
    clock = FakeClock(2000)
    listener, fake, events = await make_listener(db, clock, register=True)
    fake.published.clear()
    await listener.handle(TOPIC, b'{"id": 27, "type": "10"}')
    reply = fake.published[-1][1]
    assert reply["type"] == "11" and reply["timestamp"] == 2000
    assert reply["dev_list"] == ["FFFFFFFFFFFF"]

    with events.subscribe(TOPIC_SENSOR_UPDATED) as sub:
        await listener.handle(TOPIC, history((1990, 900), message_id=77))
        event = await sub.get()
        assert fake.published[-1][1] == {
            "ack_id": 77,
            "code": 0,
            "desc": "",
            "timestamp": 2000,
            "type": "18",
        }
        assert event.data == {
            "sensor_id": event.data["sensor_id"],
            "kind": KIND_QINGPING_MQTT,
            "metrics": {"co2": 900},
            "ts": 1990,
        }
        # старая пачка подтверждается, но свежесть не продлевает
        await listener.handle(TOPIC, history((1000, 950), message_id=78))
        assert fake.published[-1][1]["ack_id"] == 78
        # часы датчика спешат — время измерения не уходит в будущее
        await listener.handle(TOPIC, history((2100, 990), message_id=79))
        ahead = await sub.get()
        assert ahead.data["ts"] == 2000 and ahead.data["metrics"] == {"co2": 990}
        assert sub._queue.empty()


async def test_discover_requires_broker(db: Database) -> None:
    events = EventBus()
    disabled = QingpingMqttListener(db, SensorIngest(db, events), events, url=None)
    with pytest.raises(ValueError, match="EB_MQTT_URL"):
        await disabled.discover()
    offline = QingpingMqttListener(
        db, SensorIngest(db, events), events, url="mqtt://localhost"
    )
    with pytest.raises(ValueError, match="нет связи"):
        await offline.discover()


def test_providers_and_generic_registration(client_app: ClientAndApp) -> None:
    client, app = client_app
    assert client.get("/api/sensors/providers").status_code == 401
    bootstrap_admin(client, app)
    providers = {p["kind"]: p for p in client.get("/api/sensors/providers").json()}
    qingping = providers[KIND_QINGPING_MQTT]
    assert qingping["discoverable"] and qingping["manual"]
    assert "pm25" in qingping["metrics"]
    assert not providers["magicair"]["manual"]

    assert client.post("/api/sensors/discover/mqtt").status_code == 400
    assert client.post("/api/sensors/discover/nope").status_code == 404
    assert (
        client.post(
            "/api/sensors", json={"name": "M", "kind": "magicair", "address": "x"}
        ).status_code
        == 400
    )
    room = client.post("/api/rooms", json={"name": "Спальня"}).json()
    created = client.post(
        "/api/sensors",
        json={
            "name": "Воздух спальни",
            "kind": KIND_QINGPING_MQTT,
            "address": "ec4d3e7db360",
            "room_id": room["id"],
        },
    )
    assert created.status_code == 201, created.text
    sensor = created.json()
    assert sensor["source_key"] == KEY and sensor["room_id"] == room["id"]
    assert sensor["capabilities"] == [
        "co2",
        "temperature",
        "humidity",
        "pm25",
        "pm10",
        "battery",
    ]
    assert set(sensor["metric_stale"]) == set(sensor["capabilities"])
    # топики Qingping нельзя занять обычным MQTT-датчиком
    taken = client.post(
        "/api/sensors",
        json={"name": "X", "kind": "mqtt", "address": "qingping/EC4D3E7DB360"},
    )
    assert taken.status_code == 422
