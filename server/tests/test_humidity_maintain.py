"""Поддержание влажности: регулятор, движок триггеров на фейковом приборе, API."""

from __future__ import annotations

import dataclasses
import time
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from easy_breezy.automation.maintain import decide_humidity
from easy_breezy.automation.scenarios import ScenarioService
from easy_breezy.automation.triggers import TriggerEngine
from easy_breezy.config import XiaomiDeviceConfig
from easy_breezy.core.sensors import SensorIngest
from easy_breezy.integrations.xiaomi import ha2
from easy_breezy.integrations.xiaomi.ha2 import Ha2Delta, Ha2State
from easy_breezy.integrations.xiaomi.service import ApplianceService
from easy_breezy.storage.repos import SensorRepo, TriggerRepo
from tests.conftest import CoreEnv, FakeClock
from tests.fake_miio import (
    HA2_VALUES,
    TEST_DID,
    TEST_TOKEN,
    FakeMiioDevice,
    fake_transport,
)

MSK = ZoneInfo("Europe/Moscow")
NOON = datetime(2026, 10, 27, 12, 0, tzinfo=MSK).timestamp()
APPLIANCE_ID = str(TEST_DID)


def _state(**changes: Any) -> Ha2State:
    base = ha2.parse_properties(
        [
            {"siid": s, "piid": p, "code": 0, "value": v}
            for (s, p), v in HA2_VALUES.items()
        ]
    )
    return dataclasses.replace(base, **changes)


ON = Ha2Delta(
    power=True, function="humidify", humidifier_mode="fan", humidifier_fan_level=2
)
OFF = Ha2Delta(power=False)


@pytest.mark.parametrize(
    ("value", "state", "expected"),
    [
        (40, _state(power=False), ON),  # сухо, выключен → включить
        (40, _state(power=True, function="purify"), ON),  # очистка → увлажнение
        (40, _state(power=True), None),  # уже увлажняет
        (48, _state(power=False), None),  # внутри зоны покоя
        (53, _state(power=True), None),
        (54, _state(power=True), OFF),  # влажно и увлажняет → выключить
        (60, _state(power=True, function="purify"), None),  # очистку не трогаем
        (60, _state(power=False), None),
    ],
)
def test_decide_humidity(
    value: float, state: Ha2State, expected: Ha2Delta | None
) -> None:
    result = decide_humidity(
        value=value, target=50, deadband=3, state=state, fan_level=2
    )
    assert result == expected


async def test_engine_switches_appliance_by_room_sensor(core: CoreEnv) -> None:
    clock = FakeClock(NOON)
    device = FakeMiioDevice()
    device.values[(2, 1)] = False  # прибор выключен
    config = XiaomiDeviceConfig.model_validate(
        {"did": TEST_DID, "host": "fake", "token": TEST_TOKEN, "name": "Хлюпик"}
    )
    ingest = SensorIngest(core.db, core.events, now=clock.now)
    appliances = ApplianceService(
        ingest,
        core.events,
        [config],
        transport_factory=lambda _config: fake_transport(device),
        now=clock.now,
    )
    await appliances.refresh(APPLIANCE_ID)
    scenarios = ScenarioService(core.db, core.bus, core.events, appliances=appliances)
    engine = TriggerEngine(
        core.db,
        scenarios,
        core.events,
        clock,
        cache=core.cache,
        holds=core.holds,
        tz=MSK,
        appliances=appliances,
    )
    async with core.db.session() as session:
        sensor = await SensorRepo(session).create(
            kind="mqtt", name="Qingping спальня", source_key="home/air"
        )
        sensor_id = sensor.id
        trigger = await TriggerRepo(session).create(
            name="Влажность 50",
            sensor_id=sensor_id,
            metric="humidity",
            kind="maintain",
            op=">",
            threshold=50.0,
            hysteresis=3.0,
            cooldown_s=300,
            speed_max=3,
            targets=[{"target_type": "appliance", "target_id": APPLIANCE_ID}],
            enabled=True,
        )
        trigger_id = trigger.id

    assert await engine.evaluate(sensor_id, {"humidity": 40.0}, clock.now()) == 1
    await scenarios.drain()
    assert device.values[(2, 1)] is True
    assert device.values[(9, 5)] == 1
    assert device.values[(2, 3)] == 3  # режим «по скорости»
    assert device.values[(2, 14)] == 2  # скорость 3 → 2 на устройстве

    # кулдаун: влажно, но 5 минут ещё не прошло
    await clock.advance(60)
    assert await engine.evaluate(sensor_id, {"humidity": 60.0}, clock.now()) == 0
    await clock.advance(300)
    assert await engine.evaluate(sensor_id, {"humidity": 60.0}, clock.now()) == 1
    await scenarios.drain()
    assert device.values[(2, 1)] is False

    # офлайн-прибор пропускается без сжигания кулдауна
    await clock.advance(400)
    device.drop = 10
    with pytest.raises(Exception, match="нет ответа"):
        await appliances.refresh(APPLIANCE_ID)
    assert await engine.evaluate(sensor_id, {"humidity": 30.0}, clock.now()) == 0
    async with core.db.session() as session:
        stored = await TriggerRepo(session).get(trigger_id)
        assert stored is not None
        assert stored.last_fired_at == int(NOON + 360)


def test_api_humidity_maintain_validation(appliance_client: Any) -> None:
    client, _app, _device = appliance_client
    sensor_id = None
    for _ in range(50):  # прибор регистрирует свой датчик при первом опросе
        sensors = client.get("/api/sensors").json()
        if sensors:
            sensor_id = sensors[0]["id"]
            break
        time.sleep(0.05)
    assert sensor_id is not None

    base = {
        "name": "Влажность 50",
        "sensor_id": sensor_id,
        "metric": "humidity",
        "kind": "maintain",
        "threshold": 50,
        "targets": [{"target_type": "appliance", "target_id": APPLIANCE_ID}],
    }
    created = client.post("/api/triggers", json=base)
    assert created.status_code == 201, created.text
    view = created.json()
    assert view["hysteresis"] == 3.0
    assert view["cooldown_s"] == 300
    assert view["speed_max"] == 2
    assert view["speed_min"] is None

    bad_target = {**base, "targets": [{"target_type": "group", "target_id": 1}]}
    assert client.post("/api/triggers", json=bad_target).status_code == 422
    co2_on_appliance = {**base, "metric": "co2", "speed_min": 1, "speed_max": 3}
    assert client.post("/api/triggers", json=co2_on_appliance).status_code == 422
    too_wet = {**base, "threshold": 95}
    assert client.post("/api/triggers", json=too_wet).status_code == 422
    missing = {**base, "targets": [{"target_type": "appliance", "target_id": "1"}]}
    assert client.post("/api/triggers", json=missing).status_code == 404

    # второй регулятор того же прибора снимает первый (радиокнопка)
    second = client.post(
        "/api/triggers", json={**base, "name": "Ночь 45", "threshold": 45}
    )
    assert second.status_code == 201
    triggers = {t["name"]: t for t in client.get("/api/triggers").json()}
    assert triggers["Влажность 50"]["enabled"] is False
    assert triggers["Ночь 45"]["enabled"] is True
