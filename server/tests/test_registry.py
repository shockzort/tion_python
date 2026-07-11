"""Реестр устройств: запуск супервизоров, колбэки в кэш и шину событий."""

from __future__ import annotations

import asyncio

from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.core.events import (
    TOPIC_CONNECTION_CHANGED,
    TOPIC_DEVICE_LIST_CHANGED,
    TOPIC_STATE_CHANGED,
)
from easy_breezy.storage.repos import DeviceRepo
from tests.conftest import CoreEnv, wait_for_condition

MAC = "FA:KE:00:00:00:01"


async def test_start_raises_supervisors_for_paired_only(core: CoreEnv) -> None:
    async with core.db.session() as session:
        repo = DeviceRepo(session)
        paired = await repo.create(mac=MAC, name="A", created_at=1, paired=True)
        unpaired = await repo.create(
            mac="FA:KE:00:00:00:02", name="B", created_at=1, paired=False
        )

    await core.registry.start()
    assert core.registry.supervisor(unpaired.uuid) is None
    await wait_for_condition(
        lambda: core.registry.connection(paired.uuid) is ConnectionState.ONLINE
    )
    snapshot = core.cache.get(paired.uuid)
    assert snapshot is not None
    assert snapshot.state is not None  # начальное чтение прошло в кэш


async def test_callbacks_publish_events(core: CoreEnv) -> None:
    with core.events.subscribe(TOPIC_STATE_CHANGED, TOPIC_CONNECTION_CHANGED) as sub:
        device = await core.registry.add_device(mac=MAC, name="A")

        async def collect_topics() -> None:
            seen: set[str] = set()
            async for event in sub:
                assert event.data["device_uuid"] == device.uuid
                seen.add(event.topic)
                if {TOPIC_STATE_CHANGED, TOPIC_CONNECTION_CHANGED} <= seen:
                    return

        await asyncio.wait_for(collect_topics(), 3)


async def test_remove_device_stops_supervisor_and_soft_deletes(core: CoreEnv) -> None:
    with core.events.subscribe(TOPIC_DEVICE_LIST_CHANGED) as sub:
        device = await core.registry.add_device(mac=MAC, name="A")
        added = await asyncio.wait_for(sub.get(), 1)
        assert added.data == {"action": "added", "device_uuid": device.uuid}
        await wait_for_condition(
            lambda: core.registry.connection(device.uuid) is ConnectionState.ONLINE
        )

        assert await core.registry.remove_device(device.uuid)
        removed = await asyncio.wait_for(sub.get(), 1)
        assert removed.data == {"action": "removed", "device_uuid": device.uuid}

    assert core.registry.supervisor(device.uuid) is None
    assert core.cache.get(device.uuid) is None
    async with core.db.session() as session:
        stored = await DeviceRepo(session).get(device.uuid)
        assert stored is not None
        assert stored.deleted_at is not None
        assert stored.paired is False
    # повторное удаление — False, без исключений
    assert not await core.registry.remove_device(device.uuid)
