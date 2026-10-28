"""Настройки Qingping CGDN1 по MQTT: пересчёт единиц, обмен с датчиком, API."""

from __future__ import annotations

import asyncio
import json
from typing import Any, cast

import aiomqtt
import pytest

from easy_breezy.core.events import EventBus
from easy_breezy.core.sensors import KIND_QINGPING_MQTT, SensorIngest
from easy_breezy.integrations.qingping import settings
from easy_breezy.integrations.qingping.mqtt import (
    QingpingMqttListener,
    QingpingSettingsError,
)
from easy_breezy.storage import Database
from tests.conftest import ClientAndApp, FakeClock, bootstrap_admin, container_of

TOPIC = "qingping/EC4D3E7DB360/up"
KEY = "qingping_mqtt:EC:4D:3E:7D:B3:60"

# Ответ type=28 CGDN1 владельца (прошивка 4.8.5), 2026-10-28.
CONFIG: dict[str, Any] = {
    "temperature_unit": "C",
    "report_interval": 900,
    "collect_interval": 900,
    "pm_sampling_interval": 1,
    "power_off_time": 30,
    "night_mode_start_time": 0,
    "night_mode_end_time": 0,
    "display_off_time": 600,
    "auto_slideing_time": 120,
    "timezone": 30,
    "screensaver_type": 2,
    "is_12_hour_mode": 0,
    "pm25_standard": 1,
    "need_ack": 1,
    "co2_asc": 1,
    "co2_offset": 0,
    "co2_zoom": 0,
    "pm25_offset": 0,
    "pm25_zoom": 0,
    "pm10_offset": 0,
    "pm10_zoom": 0,
    "pm25_calib_mode": 0,
    "temperature_offset": 0,
    "temperature_zoom": 0,
    "humidity_offset": 0,
    "humidity_zoom": 0,
    "page_sequence": "pm25,pm10,co2,temp,pm25",
    "temp_led_th": "2300,2650,2800",
    "humi_led_th": "2000,4000,6000",
    "co2_led_th": "1000,2000,3000",
    "pm25_led_th": "35,75,115,150,250",
    "pm10_led_th": "50,150,250,350,450",
}


class FakeSensor:
    """Брокер с датчиком на том конце: отвечает на 28 и 17 как CGDN1."""

    def __init__(self, listener: QingpingMqttListener, *, ack_only: bool = False):
        self.listener = listener
        self.config = dict(CONFIG)
        self.ack_only = ack_only
        self.silent = False
        self.published: list[dict[str, Any]] = []

    async def publish(self, topic: str, payload: bytes, qos: int = 0) -> None:
        body = json.loads(payload)
        self.published.append(body)
        if self.silent:
            return
        reply: dict[str, Any] | None = None
        if body["type"] == "28":
            reply = {"type": "28", "id": 1, "setting": self.config}
        elif body["type"] == "17" and "setting" in body:
            self.config.update(body["setting"])
            reply = (
                {"type": "18", "ack_id": body["id"], "code": 0}
                if self.ack_only
                else {"type": "28", "id": 2, "setting": dict(body["setting"])}
            )
        if reply is not None:
            data = json.dumps(reply).encode()
            asyncio.get_running_loop().call_soon(
                lambda: asyncio.ensure_future(self.listener.handle(TOPIC, data))
            )


def test_from_device_converts_units() -> None:
    view = settings.from_device(CONFIG)
    assert view["screensaver"] == "time_rotate"
    assert view["timezone"] == 3.0
    assert view["is_12_hour"] is False and view["co2_asc"] is True
    assert view["display_off_time"] == 600
    assert view["co2_led_th"] == [1000, 2000, 3000]
    assert view["pm25_led_th"] == [35, 75, 115, 150, 250]
    assert (view["night_start"], view["night_end"]) == (0, 0)
    # лишнее (интервалы истории, zoom) не выставляется наружу
    assert "report_interval" not in view and "co2_zoom" not in view
    # незнакомый формат поля прошивки не роняет разбор
    assert "co2_led_th" not in settings.from_device({"co2_led_th": "a,b"})


def test_to_device_scales() -> None:
    assert settings.to_device(
        {
            "temperature_offset": -1.5,
            "humidity_offset": 2.3,
            "timezone": 3,
            "is_12_hour": False,
            "screensaver": "current",
            "co2_led_th": [800, 1200, 2000],
            "night_start": 1380,
        }
    ) == {
        "temperature_offset": -150,
        "humidity_offset": 23,
        "timezone": 30,
        "is_12_hour_mode": 0,
        "screensaver_type": 1,
        "co2_led_th": "800,1200,2000",
        "night_mode_start_time": 1380,
    }
    with pytest.raises(ValueError, match="неизвестные"):
        settings.to_device({"brightness": 3})


async def _listener(
    db: Database, *, ack_only: bool = False
) -> tuple[QingpingMqttListener, FakeSensor]:
    events = EventBus()
    clock = FakeClock(1792850078)
    listener = QingpingMqttListener(
        db,
        SensorIngest(db, events, now=clock.now),
        events,
        url="mqtt://x",
        settings_timeout=1,
    )
    sensor = FakeSensor(listener, ack_only=ack_only)
    listener._client = cast(aiomqtt.Client, sensor)
    listener.connected = True
    return listener, sensor


async def test_read_and_write_settings(db: Database) -> None:
    listener, sensor = await _listener(db)
    raw = await listener.read_settings(KEY)
    assert raw["screensaver_type"] == 2
    result = await listener.write_settings(
        KEY, {"night_mode_start_time": 1380, "night_mode_end_time": 420}
    )
    command = sensor.published[-1]
    assert command["type"] == "17" and command["id"] == command["timestamp"]
    # частичный ответ сливается с известным конфигом
    assert result["night_mode_start_time"] == 1380
    assert result["screensaver_type"] == 2


async def test_write_with_ack_only_rereads(db: Database) -> None:
    listener, sensor = await _listener(db, ack_only=True)
    result = await listener.write_settings(KEY, {"co2_asc": 0})
    assert [body["type"] for body in sensor.published] == ["17", "28"]
    assert result["co2_asc"] == 0


async def test_silent_sensor_times_out(db: Database) -> None:
    listener, sensor = await _listener(db)
    sensor.silent = True
    listener._settings_timeout = 0.05
    with pytest.raises(QingpingSettingsError, match="не ответил"):
        await listener.read_settings(KEY)
    listener._client = None
    with pytest.raises(QingpingSettingsError, match="брокер"):
        await listener.read_settings(KEY)


def test_api_sensor_settings(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    container = container_of(app)
    listener = container.qingping_mqtt
    sensor = FakeSensor(listener)
    listener._client = cast(aiomqtt.Client, sensor)

    created = client.post(
        "/api/sensors",
        json={"name": "Станция", "kind": KIND_QINGPING_MQTT, "address": "EC4D3E7DB360"},
    )
    assert created.status_code == 201, created.text
    url = f"/api/sensors/{created.json()['id']}/settings"

    current = client.get(url)
    assert current.status_code == 200, current.text
    assert current.json()["settings"]["screensaver"] == "time_rotate"

    updated = client.put(
        url, json={"humidity_offset": -2.5, "night_start": 1380, "night_end": 420}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["settings"]["humidity_offset"] == -2.5
    assert sensor.config["humidity_offset"] == -25

    assert client.put(url, json={}).status_code == 422
    assert client.put(url, json={"co2_led_th": [2000, 1000, 3000]}).status_code == 422
    assert client.put(url, json={"brightness": 1}).status_code == 422
    assert client.get("/api/sensors/999/settings").status_code == 404

    listener._client = None  # брокер недоступен — 504, а не зависание
    assert client.get(url).status_code == 504


def test_api_settings_only_for_qingping(client_app: ClientAndApp) -> None:
    client, app = client_app
    bootstrap_admin(client, app)
    created = client.post(
        "/api/sensors", json={"name": "M", "kind": "mqtt", "address": "home/air"}
    )
    assert created.status_code == 201, created.text
    response = client.get(f"/api/sensors/{created.json()['id']}/settings")
    assert response.status_code == 400
