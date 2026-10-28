"""Приборы Xiaomi: сервис опроса/команд, сценарии и REST на фейковом miIO."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import structlog

from easy_breezy.automation.scenarios import ScenarioService
from easy_breezy.config import XiaomiDeviceConfig
from easy_breezy.core.events import TOPIC_APPLIANCE_STATE_CHANGED, EventBus
from easy_breezy.core.sensors import KIND_XIAOMI_MIIO, SensorIngest
from easy_breezy.integrations.xiaomi.ha2 import ApplianceDeltaError, Ha2Delta
from easy_breezy.integrations.xiaomi.service import (
    ApplianceError,
    ApplianceNotFoundError,
    ApplianceService,
    sensor_source_key,
)
from easy_breezy.storage import Database
from easy_breezy.storage.models import CommandSource
from easy_breezy.storage.repos import SensorRepo
from tests.conftest import (
    CoreEnv,
    container_of,
    wait_for_condition,
)
from tests.fake_miio import TEST_DID, TEST_TOKEN, FakeMiioDevice, fake_transport

APPLIANCE_ID = str(TEST_DID)


def _config() -> XiaomiDeviceConfig:
    return XiaomiDeviceConfig.model_validate(
        {"did": TEST_DID, "host": "fake", "token": TEST_TOKEN, "name": "Хлюпик"}
    )


class Clock:
    def __init__(self) -> None:
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        return self.now


def _service(
    db: Database, events: EventBus, device: FakeMiioDevice, clock: Clock | None = None
) -> ApplianceService:
    return ApplianceService(
        SensorIngest(db, events, now=clock or Clock()),
        events,
        [_config()],
        transport_factory=lambda _config: fake_transport(device),
        now=clock or Clock(),
        settle_delay=0,
    )


def test_config_rejects_bad_token() -> None:
    with pytest.raises(ValueError, match="32 hex"):
        XiaomiDeviceConfig.model_validate(
            {"did": 1, "host": "h", "token": "nothex", "name": "x"}
        )


async def test_refresh_publishes_state_and_registers_sensor(db: Database) -> None:
    events = EventBus()
    device = FakeMiioDevice()
    service = _service(db, events, device)
    with events.subscribe(TOPIC_APPLIANCE_STATE_CHANGED) as sub:
        snapshot = await service.refresh(APPLIANCE_ID)
        event = await asyncio.wait_for(sub.get(), 1)
    assert snapshot.online and snapshot.state is not None
    assert event.data["state"]["target_humidity"] == 55
    # опрос пачками: ни один запрос не превышает лимит устройства
    assert all(len(r["params"]) <= 10 for r in device.requests)
    async with db.session() as session:
        sensor = await SensorRepo(session).get_by_source_key(
            sensor_source_key(TEST_DID)
        )
    assert sensor is not None
    assert sensor.kind == KIND_XIAOMI_MIIO
    assert sensor.name == "Хлюпик"
    assert sensor.last_values == {"humidity": 55.0, "temperature": 24.0, "pm25": 3.0}


async def test_unchanged_state_publishes_nothing(db: Database) -> None:
    events = EventBus()
    service = _service(db, events, FakeMiioDevice())
    await service.refresh(APPLIANCE_ID)
    with events.subscribe(TOPIC_APPLIANCE_STATE_CHANGED) as sub:
        await service.refresh(APPLIANCE_ID)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(sub.get(), 0.05)


async def test_offline_marks_snapshot(db: Database) -> None:
    events = EventBus()
    device = FakeMiioDevice()
    service = _service(db, events, device)
    await service.refresh(APPLIANCE_ID)
    device.drop = 10
    with pytest.raises(Exception, match="нет ответа"):
        await service.refresh(APPLIANCE_ID)
    snapshot = service.get(APPLIANCE_ID)
    assert snapshot is not None and not snapshot.online
    assert snapshot.state is not None  # последнее известное состояние не теряем
    assert snapshot.error is not None


async def test_command_applies_and_confirms(db: Database) -> None:
    device = FakeMiioDevice()
    service = _service(db, EventBus(), device)
    snapshot = await service.command(
        APPLIANCE_ID,
        Ha2Delta(target_humidity=60, humidifier_mode="constant"),
        source="ui",
    )
    assert device.values[(2, 6)] == 60
    assert device.values[(2, 3)] == 0
    assert snapshot.state is not None
    assert snapshot.state.target_humidity == 60
    assert snapshot.state.humidifier_mode == "constant"


async def test_command_waits_until_device_applies(db: Database) -> None:
    # прибор применяет запись не сразу: первый полный опрос (4 запроса) ещё
    # видит старый режим — ответ команды не должен его вернуть
    device = FakeMiioDevice(apply_lag=4)
    service = _service(db, EventBus(), device)
    await service.refresh(APPLIANCE_ID)
    snapshot = await service.command(
        APPLIANCE_ID, Ha2Delta(humidifier_mode="sleep"), source="ui"
    )
    assert snapshot.state is not None
    assert snapshot.state.humidifier_mode == "sleep"


async def test_poll_does_not_interleave_with_command(db: Database) -> None:
    # опрос и команда под одним замком: в кэш не попадает смесь состояний
    events = EventBus()
    device = FakeMiioDevice()
    service = _service(db, events, device)
    await service.refresh(APPLIANCE_ID)
    with events.subscribe(TOPIC_APPLIANCE_STATE_CHANGED) as sub:
        await asyncio.gather(
            service.refresh(APPLIANCE_ID),
            service.command(
                # поля из первой и последней пачки опроса
                APPLIANCE_ID,
                Ha2Delta(power=False, screen_brightness="dim"),
                source="ui",
            ),
            service.refresh(APPLIANCE_ID),
        )
        states = []
        while True:
            try:
                event = await asyncio.wait_for(sub.get(), 0.05)
            except TimeoutError:
                break
            states.append(event.data["state"])
    assert states, "команда должна опубликовать новое состояние"
    # ни одного «полуприменённого» состояния
    assert all(
        (state["power"], state["screen_brightness"]) == (False, "dim")
        for state in states
    )


async def test_config_fields_round_trip(db: Database) -> None:
    device = FakeMiioDevice()
    service = _service(db, EventBus(), device)
    snapshot = await service.refresh(APPLIANCE_ID)
    assert snapshot.state is not None
    assert snapshot.state.night_mode is True
    assert (snapshot.state.night_start, snapshot.state.night_end) == (1380, 600)
    assert snapshot.state.screen_brightness == "auto"
    snapshot = await service.command(
        APPLIANCE_ID,
        Ha2Delta(
            screen_brightness="dim",
            night_start=1320,
            night_end=420,
            off_timer_hours=3,
            off_timer=True,
            display_metric="pm10",
        ),
        source="ui",
    )
    assert device.values[(5, 2)] == 3
    assert device.values[(9, 7)] == 1320
    assert device.values[(9, 21)] == 2
    assert snapshot.state is not None and snapshot.state.off_timer_hours == 3
    # длительность таймера пишется раньше включения
    sets = [r for r in device.requests if r["method"] == "set_properties"][-1]
    pairs = [(p["siid"], p["piid"]) for p in sets["params"]]
    assert pairs.index((13, 2)) < pairs.index((13, 1))


@pytest.mark.parametrize(
    "payload",
    [
        {"night_start": 1440},
        {"purifier_favorite_level": 10},
        {"off_timer_hours": 0},
        {"screen_brightness": "max"},
        {"display_metric": "co2"},
        {"night_mode": 1},
    ],
)
def test_delta_rejects_bad_config(payload: dict[str, Any]) -> None:
    with pytest.raises(ApplianceDeltaError):
        Ha2Delta.from_payload(payload)


async def test_action_calls_device(db: Database) -> None:
    device = FakeMiioDevice()
    service = _service(db, EventBus(), device)
    snapshot = await service.action(APPLIANCE_ID, "self_clean_start", source="ui")
    assert device.actions == [(12, 1)]
    assert snapshot.online
    with pytest.raises(ApplianceError, match="действие"):
        await service.action(APPLIANCE_ID, "explode", source="ui")


async def test_unreachable_from_start_is_logged(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    device = FakeMiioDevice(drop=100)
    service = _service(db, EventBus(), device)
    with structlog.testing.capture_logs() as logs:
        for _ in range(2):
            with pytest.raises(Exception, match="нет ответа"):
                await service.refresh(APPLIANCE_ID)
    events = [entry["event"] for entry in logs]
    # с самого старта — тоже предупреждение, но одно, а не на каждый опрос
    assert events.count("appliance_unreachable") == 1


async def test_command_rejected_property(db: Database) -> None:
    device = FakeMiioDevice(reject={(2, 6)})
    service = _service(db, EventBus(), device)
    with pytest.raises(ApplianceError, match="target_humidity"):
        await service.command(APPLIANCE_ID, Ha2Delta(target_humidity=60), source="ui")


async def test_command_unknown_appliance(db: Database) -> None:
    service = _service(db, EventBus(), FakeMiioDevice())
    with pytest.raises(ApplianceNotFoundError):
        await service.command("42", Ha2Delta(power=False), source="ui")


async def test_poll_loop_recovers_after_outage(db: Database) -> None:
    device = FakeMiioDevice(drop=2)  # первый опрос падает целиком
    service = ApplianceService(
        SensorIngest(db, EventBus()),
        EventBus(),
        [_config()],
        transport_factory=lambda _config: fake_transport(device),
        poll_interval=0.01,
        jitter=lambda: 0.0,
    )
    await service.start()
    try:
        await wait_for_condition(lambda: bool(service.list()[0].online), timeout=5)
    finally:
        await service.stop()


async def test_scenario_appliance_action(core: CoreEnv) -> None:
    device = FakeMiioDevice()
    appliances = _service(core.db, core.events, device)
    scenarios = ScenarioService(core.db, core.bus, core.events, appliances=appliances)
    submissions = await scenarios.run_actions(
        [
            {
                "target_type": "appliance",
                "target_id": APPLIANCE_ID,
                "delta": {"power": False},
            },
            {
                "target_type": "appliance",
                "target_id": APPLIANCE_ID,
                "delta": {"target_humidity": 45},
            },
        ],
        source=CommandSource.SCHEDULE,
        idempotency_prefix="test",
    )
    assert submissions == []  # приборы не ставятся в журнал команд бризеров
    await scenarios.drain()
    assert device.values[(2, 1)] is False
    assert device.values[(2, 6)] == 45
    sets = [r for r in device.requests if r["method"] == "set_properties"]
    assert len(sets) == 1  # действия одного прибора смержены в одну команду


# --- REST ----------------------------------------------------------------------


def test_api_list_and_command(appliance_client: Any) -> None:
    client, app, device = appliance_client
    container = container_of(app)
    assert container.appliances.get(APPLIANCE_ID) is not None

    response = client.post(
        f"/api/appliances/{APPLIANCE_ID}/command", json={"target_humidity": 65}
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"]["target_humidity"] == 65
    assert device.values[(2, 6)] == 65

    listing = client.get("/api/appliances").json()
    assert [a["id"] for a in listing] == [APPLIANCE_ID]
    assert listing[0]["online"] is True

    assert (
        client.post(
            f"/api/appliances/{APPLIANCE_ID}/command", json={"target_humidity": 90}
        ).status_code
        == 422
    )
    assert (
        client.post(f"/api/appliances/{APPLIANCE_ID}/command", json={}).status_code
        == 422
    )
    assert (
        client.post("/api/appliances/1/command", json={"power": True}).status_code
        == 404
    )


def test_api_config_and_action(appliance_client: Any) -> None:
    client, _app, device = appliance_client
    base = f"/api/appliances/{APPLIANCE_ID}"
    response = client.post(
        f"{base}/command", json={"night_mode": False, "screen_brightness": "medium"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"]["night_mode"] is False
    assert device.values[(5, 2)] == 2
    assert client.post(f"{base}/command", json={"night_end": 2000}).status_code == 422

    response = client.post(f"{base}/action", json={"action": "reset_humidifier_filter"})
    assert response.status_code == 200, response.text
    assert device.actions == [(15, 1)]
    assert client.post(f"{base}/action", json={"action": "boom"}).status_code == 422
    assert (
        client.post("/api/appliances/1/action", json={"action": "dry_stop"}).status_code
        == 404
    )


def test_api_scenario_with_appliance_target(appliance_client: Any) -> None:
    client, _app, _device = appliance_client
    good = client.post(
        "/api/scenarios",
        json={
            "name": "Ночь",
            "actions": [
                {
                    "target_type": "appliance",
                    "target_id": APPLIANCE_ID,
                    "delta": {"power": True, "humidifier_mode": "sleep"},
                }
            ],
        },
    )
    assert good.status_code == 201, good.text
    assert good.json()["actions"][0]["delta"] == {
        "power": True,
        "humidifier_mode": "sleep",
    }
    missing = client.post(
        "/api/scenarios",
        json={
            "name": "Нет прибора",
            "actions": [
                {"target_type": "appliance", "target_id": "1", "delta": {"power": True}}
            ],
        },
    )
    assert missing.status_code == 404
    wrong_delta = client.post(
        "/api/scenarios",
        json={
            "name": "Бризер-дельта",
            "actions": [
                {
                    "target_type": "appliance",
                    "target_id": APPLIANCE_ID,
                    "delta": {"fan_speed": 3},
                }
            ],
        },
    )
    assert wrong_delta.status_code == 422
