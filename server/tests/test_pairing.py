"""Мастер сопряжения: разбор рекламы и реанимация удалённых устройств."""

from __future__ import annotations

from easy_breezy.ble.scanner import pairing_mode_from_adv
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.storage.repos import DeviceRepo
from tests.conftest import CoreEnv, wait_for_condition

MAC = "FA:KE:00:00:00:01"


def test_pairing_mode_from_adv() -> None:
    mac_le = bytes.fromhex("1490a49f82ec")
    normal = {0xFFFF: mac_le + bytes.fromhex("038000 00 00".replace(" ", ""))}
    pairing = {0xFFFF: mac_le + bytes.fromhex("038000 00 01".replace(" ", ""))}
    assert pairing_mode_from_adv(normal) is False
    assert pairing_mode_from_adv(pairing) is True
    assert pairing_mode_from_adv({}) is None  # рекламы Tion нет
    assert pairing_mode_from_adv({0xFFFF: b"\x01\x02"}) is None  # короткий payload
    assert pairing_mode_from_adv({0x004C: mac_le * 2}) is None  # чужая компания


async def test_add_device_revives_soft_deleted(core: CoreEnv) -> None:
    device = await core.registry.add_device(mac=MAC, name="Старый")
    await wait_for_condition(
        lambda: core.registry.connection(device.uuid) is ConnectionState.ONLINE
    )
    assert await core.registry.remove_device(device.uuid)

    revived = await core.registry.add_device(mac=MAC, name="Новый")
    assert revived.uuid == device.uuid  # та же запись — журнал не осиротел
    assert revived.name == "Новый"
    await wait_for_condition(
        lambda: core.registry.connection(revived.uuid) is ConnectionState.ONLINE
    )
    async with core.db.session() as session:
        stored = await DeviceRepo(session).get(device.uuid)
        assert stored is not None
        assert stored.deleted_at is None
        assert stored.paired is True
