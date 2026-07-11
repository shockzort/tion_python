"""Слой storage: миграции Alembic, репозитории, ограничения схемы."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from easy_breezy.storage import Database
from easy_breezy.storage.models import CommandStatus
from easy_breezy.storage.repos import (
    CommandRepo,
    DeviceRepo,
    GroupRepo,
    SettingsRepo,
    TelemetryPoint,
    TelemetryRepo,
)


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    await database.migrate()
    yield database
    await database.dispose()


async def test_migrate_creates_full_schema(db: Database) -> None:
    """alembic upgrade head поднимает все таблицы плана §5."""

    async with db.engine.connect() as conn:
        tables = await conn.run_sync(lambda sync: set(inspect(sync).get_table_names()))
    expected = {
        "rooms",
        "devices",
        "device_groups",
        "device_group_members",
        "commands",
        "scenarios",
        "schedules",
        "triggers",
        "sensors",
        "telemetry_raw",
        "telemetry_hourly",
        "users",
        "sessions",
        "api_tokens",
        "oauth_codes",
        "oauth_tokens",
        "settings",
        "push_subscriptions",
    }
    assert expected <= tables
    # повторный migrate — no-op (идемпотентность)
    await db.migrate()


async def test_device_crud_and_soft_delete(db: Database) -> None:
    async with db.session() as session:
        repo = DeviceRepo(session)
        device = await repo.create(
            mac="ec:82:9f:a4:90:14", name="Ближний", created_at=100, paired=True
        )
        assert device.mac == "EC:82:9F:A4:90:14"  # нормализация MAC

    async with db.session() as session:
        repo = DeviceRepo(session)
        found = await repo.get_by_mac("EC:82:9F:A4:90:14")
        assert found is not None and found.uuid == device.uuid
        assert [d.uuid for d in await repo.list_active()] == [device.uuid]
        await repo.soft_delete(found, deleted_at=200)

    async with db.session() as session:
        repo = DeviceRepo(session)
        assert await repo.list_active() == []
        survivor = await repo.get(device.uuid)  # журнал ссылается — строка живёт
        assert survivor is not None and survivor.deleted_at == 200


async def test_command_journal_lifecycle(db: Database) -> None:
    async with db.session() as session:
        device = await DeviceRepo(session).create(
            mac="D0:60:0E:F7:EA:D4", name="Средний", created_at=100
        )
        repo = CommandRepo(session)
        record = await repo.insert(
            idempotency_key="ui:abc",
            device_uuid=device.uuid,
            source="ui",
            priority=0,
            payload={"fan_speed": 3},
            created_at=100,
        )
        await repo.mark_running(record.id, started_at=101)
        await repo.finish(
            record.id,
            status=CommandStatus.DONE,
            finished_at=102,
            result_state={"fan_speed": 3},
        )

    async with db.session() as session:
        repo = CommandRepo(session)
        saved = await repo.get_by_key("ui:abc")
        assert saved is not None
        assert saved.status == CommandStatus.DONE
        assert saved.result_state == {"fan_speed": 3}

        # дубль ключа идемпотентности отбивается схемой
        with pytest.raises(IntegrityError):
            await repo.insert(
                idempotency_key="ui:abc",
                device_uuid=device.uuid,
                source="ui",
                priority=0,
                payload={},
                created_at=103,
            )


async def test_fail_interrupted_marks_stale_commands(db: Database) -> None:
    async with db.session() as session:
        device = await DeviceRepo(session).create(
            mac="EB:B5:4E:13:31:B5", name="Дальний", created_at=100
        )
        repo = CommandRepo(session)
        pending = await repo.insert(
            idempotency_key="k1",
            device_uuid=device.uuid,
            source="ui",
            priority=0,
            payload={},
            created_at=100,
        )
        running = await repo.insert(
            idempotency_key="k2",
            device_uuid=device.uuid,
            source="ui",
            priority=0,
            payload={},
            created_at=100,
        )
        await repo.mark_running(running.id, started_at=101)

    async with db.session() as session:
        assert await CommandRepo(session).fail_interrupted(finished_at=200) == 2

    async with db.session() as session:
        repo = CommandRepo(session)
        for command_id in (pending.id, running.id):
            record = await repo.get(command_id)
            assert record is not None
            assert record.status == CommandStatus.FAILED
            assert record.error == "прерван рестартом сервиса"


async def test_groups_membership_replacement(db: Database) -> None:
    async with db.session() as session:
        devices = DeviceRepo(session)
        first = await devices.create(mac="AA:00:00:00:00:01", name="1", created_at=1)
        second = await devices.create(mac="AA:00:00:00:00:02", name="2", created_at=1)
        groups = GroupRepo(session)
        group = await groups.create("Спальня")
        await groups.set_members(group.id, [first.uuid, second.uuid])

    async with db.session() as session:
        groups = GroupRepo(session)
        assert set(await groups.members(group.id)) == {first.uuid, second.uuid}
        await groups.set_members(group.id, [second.uuid])
        assert await groups.members(group.id) == [second.uuid]


async def test_settings_upsert(db: Database) -> None:
    async with db.session() as session:
        repo = SettingsRepo(session)
        assert await repo.get("tz", "Europe/Moscow") == "Europe/Moscow"
        await repo.set("tz", "Asia/Novosibirsk")

    async with db.session() as session:
        repo = SettingsRepo(session)
        assert await repo.get("tz") == "Asia/Novosibirsk"
        await repo.set("tz", {"name": "UTC", "offset": 0})  # JSON произвольной формы

    async with db.session() as session:
        assert await SettingsRepo(session).get("tz") == {"name": "UTC", "offset": 0}


async def test_telemetry_downsample_and_purge(db: Database) -> None:
    hour = 36_000
    async with db.session() as session:
        repo = TelemetryRepo(session)
        await repo.add_points(
            TelemetryPoint(hour + i, "device", "dev-1", "out_temp", float(20 + i))
            for i in range(3)
        )
        await repo.add_points(
            [TelemetryPoint(hour - 1, "device", "dev-1", "out_temp", 15.0)]
        )

    async with db.session() as session:
        assert await TelemetryRepo(session).downsample_hour(hour) == 1

    async with db.session() as session:
        repo = TelemetryRepo(session)
        # пересчёт того же часа идемпотентен
        assert await repo.downsample_hour(hour) == 1
        raw_deleted, _ = await repo.purge(raw_before=hour, hourly_before=0)
        assert raw_deleted == 1  # точка до начала часа
