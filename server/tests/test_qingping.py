"""Записанные CGDN1-пакеты → свежесть, история, управление; BLE без оборудования."""

from __future__ import annotations

import asyncio
from datetime import UTC
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import select

from easy_breezy.automation.clock import SystemClock
from easy_breezy.automation.scenarios import ScenarioService
from easy_breezy.automation.triggers import TriggerEngine
from easy_breezy.ble.coordinator import ScanCoordinator
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.events import (
    TOPIC_COMMAND_FINISHED,
    TOPIC_SENSOR_UPDATED,
    EventBus,
)
from easy_breezy.core.sensors import SensorIngest
from easy_breezy.core.telemetry import TelemetryService
from easy_breezy.integrations.qingping import client as qingping_client
from easy_breezy.integrations.qingping.client import QingpingListener
from easy_breezy.integrations.qingping.parser import parse_advertisement, source_key
from easy_breezy.storage import Database
from easy_breezy.storage.database import alembic_config
from easy_breezy.storage.models import TelemetryRaw
from easy_breezy.storage.repos import SensorRepo, TriggerRepo
from tests.conftest import (
    ClientAndApp,
    CoreEnv,
    FakeClock,
    bootstrap_admin,
    wait_for_condition,
)

# qingping-ble tests/test_parser.py, commit da63385cb7fd8ecb06323b6077d17023fa17340e
# MIT; исходные пакеты AIR_MONITOR и AIR_MONITOR_DEV_TYPE_36.
PACKET = bytes.fromhex("880ed6888fe6485401040301160212040200020013022502")
PACKET_36 = bytes.fromhex("88246b4dc994c27c0104fd00490212040900090013026102")
KEY = "qingping_ble:54:48:E6:8F:88:D6"


@pytest.mark.parametrize(
    ("packet", "expected"),
    [
        (
            PACKET,
            {"temperature": 25.9, "humidity": 53.4, "co2": 549, "pm25": 2, "pm10": 2},
        ),
        (
            PACKET_36,
            {"temperature": 25.3, "humidity": 58.5, "co2": 609, "pm25": 9, "pm10": 9},
        ),
    ],
)
def test_recorded_cgdn1(packet: bytes, expected: dict[str, float]) -> None:
    reading = parse_advertisement(packet)
    assert reading is not None and reading.metrics == expected


def test_partial_packet_never_carries_previous_co2() -> None:
    assert parse_advertisement(PACKET) is not None
    reading = parse_advertisement(PACKET[:14])
    assert reading is not None and reading.source_key == KEY
    assert reading.metrics == {"temperature": 25.9, "humidity": 53.4}
    assert parse_advertisement(PACKET[:-1]) is None
    assert parse_advertisement(PACKET[:1]) is None
    assert parse_advertisement(PACKET[:1] + b"\x01" + PACKET[2:]) is None
    assert parse_advertisement(PACKET[:8] + b"\x13\x02\xff\xff") is None
    assert parse_advertisement(PACKET[:8] + b"\x01\x04\xff\x7f\xff\xff") is None
    assert source_key("54:48:e6:8f:88:d6") == KEY
    with pytest.raises(ValueError):
        source_key("not a MAC")


async def test_sampling_partial_freshness_and_measurement_time(db: Database) -> None:
    clock = FakeClock(1000)
    events = EventBus()
    ingest = SensorIngest(db, events, now=clock.now)
    listener = QingpingListener(db, ingest, events, ScanCoordinator(), now=clock.now)
    async with db.session() as session:
        sensor = await SensorRepo(session).create(
            kind="qingping_ble", name="Q", source_key=KEY
        )
        sensor_id = sensor.id
    await listener.reload()
    with events.subscribe(TOPIC_SENSOR_UPDATED) as sub:
        listener.receive(PACKET)
        await listener.flush()
        first = await sub.get()
        assert first.data["metrics"]["co2"] == 549
        await clock.advance(1)
        listener.receive(PACKET)
        await listener.flush()
        assert sub._queue.empty()
        await clock.advance(4)
        listener.receive(PACKET[:14])
        await clock.advance(25)
        await listener.flush()
        buffered = [await sub.get(), await sub.get()]
        assert {(e.data["ts"], frozenset(e.data["metrics"])) for e in buffered} == {
            (1001, frozenset({"co2", "pm25", "pm10"})),
            (1005, frozenset({"temperature", "humidity"})),
        }
        # Молчание не производит события из старого кэша.
        await clock.advance(301)
        await listener.flush()
        assert sub._queue.empty()
        listener.receive(PACKET[:14])
        await listener.flush()
        assert "co2" not in (await sub.get()).data["metrics"]
        async with db.session() as session:
            stored = await SensorRepo(session).get(sensor_id)
            assert stored is not None
            assert stored.last_metric_at == {
                "co2": 1001,
                "pm25": 1001,
                "pm10": 1001,
                "temperature": 1331,
                "humidity": 1331,
            }
        # Продолжающиеся одинаковые CO₂ также доставляются.
        listener.receive(PACKET)
        await listener.flush()
        assert (await sub.get()).data["metrics"] == {"co2": 549, "pm25": 2, "pm10": 2}

    # Время точки — приём пакета, а не время flush/обработки.
    telemetry = TelemetryService(db, events, now=lambda: 9999)
    await telemetry._record(first)
    async with db.session() as session:
        points = list((await session.execute(select(TelemetryRaw))).scalars())
    assert len(points) == 5 and {point.ts for point in points} == {1000}
    # Неизвестный CGDN1 не регистрируется и не растит буфер.
    listener.receive(PACKET_36)
    assert all(key[0] == KEY for key in listener._pending)
    async with db.session() as session:
        stored = await SensorRepo(session).get(sensor_id)
        assert stored is not None
        await SensorRepo(session).delete(stored)
    await listener.reload()
    assert not listener._pending and not listener._published


async def test_qingping_controls_existing_maintain_and_respects_age(
    core: CoreEnv,
) -> None:
    device = await core.registry.add_device(mac="FA:KE:00:00:00:01", name="Тест")
    await wait_for_condition(
        lambda: core.registry.connection(device.uuid) is ConnectionState.ONLINE
    )
    await wait_for_condition(
        lambda: (snap := core.cache.get(device.uuid)) is not None
        and snap.state is not None
    )
    now = SystemClock().now()
    clock = FakeClock(now)
    ingest = SensorIngest(core.db, core.events, now=clock.now)
    listener = QingpingListener(
        core.db, ingest, core.events, ScanCoordinator(), now=clock.now
    )
    async with core.db.session() as session:
        sensor = await SensorRepo(session).create(
            kind="qingping_ble", name="Q", source_key=KEY
        )
        sid = sensor.id
        await TriggerRepo(session).create(
            name="Поддержание",
            sensor_id=sid,
            kind="maintain",
            metric="co2",
            op=">",
            threshold=800,
            hysteresis=50,
            cooldown_s=120,
            speed_min=1,
            speed_max=6,
            targets=[{"target_type": "device", "target_id": device.uuid}],
        )
    engine = TriggerEngine(
        core.db,
        ScenarioService(core.db, core.bus, core.events),
        core.events,
        clock,
        cache=core.cache,
        holds=core.holds,
        tz=UTC,
    )
    await listener.reload()
    with core.events.subscribe(TOPIC_SENSOR_UPDATED) as sub:
        # Записанный пакет с CO₂=1500, остальные поля без изменений.
        listener.receive(PACKET[:-2] + (1500).to_bytes(2, "little"))
        await listener.flush()
        event = await sub.get()
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as commands:
        assert await engine.evaluate(sid, event.data["metrics"], event.data["ts"]) == 1
        result = await asyncio.wait_for(commands.get(), 2)
    assert result.data["result_state"]["fan_speed"] == 4
    await clock.advance(301)
    assert await engine.evaluate(sid, event.data["metrics"], event.data["ts"]) == 0
    assert await engine.evaluate(sid, {"temperature": 26}, clock.now()) == 0
    core.holds.place(device.uuid)
    assert await engine.evaluate(sid, {"co2": 1500}, clock.now()) == 0
    core.holds.release(device.uuid)
    with core.events.subscribe(TOPIC_COMMAND_FINISHED) as commands:
        assert await engine.evaluate(sid, {"co2": 1500}, clock.now()) == 1
        assert (await asyncio.wait_for(commands.get(), 2)).data["status"] == "done"


async def test_background_yields_and_cancelled_foreground_does_not_stall() -> None:
    gate = ScanCoordinator()
    order: list[str] = []

    async def foreground() -> None:
        async with gate:
            order.append("tion")

    async with gate.background() as interrupted:
        task = asyncio.create_task(foreground())
        await asyncio.wait_for(interrupted.wait(), 1)
        assert not order
    await task
    async with gate.background() as interrupted:
        task = asyncio.create_task(foreground())
        await interrupted.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    async with gate.background():
        order.append("qingping")
    assert order == ["tion", "qingping"]
    assert not gate.locked()


async def test_listener_idle_retry_preemption_and_stop(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = EventBus()
    gate = ScanCoordinator()
    active = 0
    starts = 0

    class FakeScanner:
        def __init__(self, **kwargs: object) -> None:
            assert kwargs["bluez"] == {"filters": {"DuplicateData": True}}
            self.active = False

        async def start(self) -> None:
            nonlocal starts, active
            starts += 1
            if starts == 1:
                raise OSError("adapter unavailable")
            active += 1
            self.active = True

        async def stop(self) -> None:
            nonlocal active
            if self.active:
                active -= 1

    monkeypatch.setattr(qingping_client, "BleakScanner", FakeScanner)
    listener = QingpingListener(db, SensorIngest(db, events), events, gate)
    await listener.start()
    try:
        await asyncio.sleep(0)
        assert starts == 0  # выкладка без CGDN1 не меняет радио
        async with db.session() as session:
            await SensorRepo(session).create(
                kind="qingping_ble", name="Q", source_key=KEY
            )
        await listener.reload()
        await wait_for_condition(lambda: active == 1)
        assert starts == 2 and listener.last_error is None
        async with gate:
            assert active == 0
        await wait_for_condition(lambda: active == 1)
        assert starts == 3
        discovery = asyncio.create_task(listener.discover(duration=0.05))
        await asyncio.sleep(0)
        listener.receive(PACKET, -42)
        found = await discovery
        assert len(found) == 1 and found[0].registered and found[0].signal_dbm == -42
    finally:
        await listener.stop()
    assert active == 0 and not gate.locked()


async def test_listener_renews_scan_after_silent_session_loss(
    db: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = EventBus()
    gate = ScanCoordinator()
    starts = 0
    stops = 0

    class FakeScanner:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def start(self) -> None:
            nonlocal starts
            starts += 1  # после start поток молчит, исключения нет

        async def stop(self) -> None:
            nonlocal stops
            stops += 1

    monkeypatch.setattr(qingping_client, "BleakScanner", FakeScanner)
    monkeypatch.setattr(qingping_client, "SCAN_SESSION_SECONDS", 0.02)
    async with db.session() as session:
        await SensorRepo(session).create(kind="qingping_ble", name="Q", source_key=KEY)
    listener = QingpingListener(db, SensorIngest(db, events), events, gate)
    await listener.start()
    try:
        await wait_for_condition(lambda: starts >= 2)
        assert stops >= 1 and listener.last_error is None
        async with db.session() as session:
            sensor = (await SensorRepo(session).list_all())[0]
        assert sensor.last_seen_at is None  # рестарт не создаёт измерений
    finally:
        await listener.stop()
    assert starts == stops and not gate.locked()


def test_qingping_registration_and_backward_compatible_mqtt(
    client_app: ClientAndApp,
) -> None:
    client, app = client_app
    assert client.post("/api/sensors/discover/qingping_ble").status_code == 401
    bootstrap_admin(client, app)
    room = client.post("/api/rooms", json={"name": "Комната"}).json()
    result = client.post(
        "/api/sensors",
        json={
            "kind": "qingping_ble",
            "name": "Q",
            "address": "54:48:e6:8f:88:d6",
            "room_id": room["id"],
        },
    )
    assert result.status_code == 201
    sensor = result.json()
    assert sensor["source_key"] == KEY and sensor["stale"]
    assert all(sensor["metric_stale"].values()) and sensor["last_metric_at"] is None
    assert (
        client.post(
            "/api/sensors",
            json={"kind": "qingping_ble", "name": "Q2", "address": KEY},
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/sensors",
            json={"kind": "qingping_ble", "name": "Q", "address": "garbage"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/sensors", json={"name": "Q", "kind": "mqtt", "address": KEY}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/sensors", json={"name": "M", "kind": "mqtt", "address": "home/air"}
        ).json()["kind"]
        == "mqtt"
    )
    changed = client.patch(
        f"/api/sensors/{sensor['id']}", json={"room_id": None, "name": "Новое имя"}
    ).json()
    assert changed["room_id"] is None and changed["name"] == "Новое имя"
    assert client.delete(f"/api/sensors/{sensor['id']}").status_code == 204


async def test_migration_keeps_old_values_without_inventing_freshness(
    tmp_path: Path,
) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'old.db'}"
    await asyncio.to_thread(command.upgrade, alembic_config(url), "0004")
    import sqlite3

    with sqlite3.connect(tmp_path / "old.db") as connection:
        connection.execute(
            "INSERT INTO sensors (kind, name, source_key, last_values, last_seen_at) "
            "VALUES ('mqtt', 'Old', 'air', '{\"co2\":900}', 1000)"
        )
    database = Database(url)
    try:
        await database.migrate()
        await database.migrate()
        async with database.session() as session:
            sensor = (await SensorRepo(session).list_all())[0]
        assert sensor.last_values == {"co2": 900}
        assert sensor.last_metric_at is None
    finally:
        await database.dispose()
