"""Unit tests for DeviceManager — integration with storage and API layer."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from tion_btle.domain.device_manager.device_manager import DeviceManager
from tion_btle.domain.device_manager.models import DeviceInfo
from tion_btle.domain.device_manager.interfaces import IDeviceStorage, IDeviceGroupStorage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_device_storage() -> MagicMock:
    """In-memory mock of IDeviceStorage."""
    storage = MagicMock(spec=IDeviceStorage)
    storage.get_devices.return_value = []
    storage.get_device.return_value = None
    storage.create_device.return_value = True
    storage.update_device.return_value = True
    storage.delete_device.return_value = True
    return storage


@pytest.fixture
def mock_group_storage() -> MagicMock:
    """In-memory mock of IDeviceGroupStorage."""
    storage = MagicMock(spec=IDeviceGroupStorage)
    storage.get_groups.return_value = []
    storage.create_group.return_value = 1
    storage.update_group.return_value = True
    storage.delete_group.return_value = True
    return storage


@pytest.fixture
def device_manager(mock_device_storage: MagicMock, mock_group_storage: MagicMock) -> DeviceManager:
    """DeviceManager instance backed by mock storages."""
    return DeviceManager(mock_device_storage, mock_group_storage)


@pytest.fixture
def sample_device_info() -> DeviceInfo:
    """A sample registered DeviceInfo."""
    return DeviceInfo(
        id="AA:BB:CC:DD:EE:FF",
        name="Living Room",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
        is_active=True,
        is_paired=False,
        room="Living Room",
    )


# ---------------------------------------------------------------------------
# Test-1: test_register_device_success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_device_success(
    device_manager: DeviceManager, mock_device_storage: MagicMock
) -> None:
    """register_device with valid kwargs creates DeviceInfo and stores it."""
    result = await device_manager.register_device(
        name="Living Room",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
    )

    assert result.name == "Living Room"
    assert result.mac_address == "AA:BB:CC:DD:EE:FF"
    assert result.model == "S3"
    assert result.type == "TionS3"
    assert result.id == "AA:BB:CC:DD:EE:FF"
    assert result.is_active is True
    mock_device_storage.create_device.assert_called_once()


# ---------------------------------------------------------------------------
# Test-2: test_register_device_duplicate_mac (upsert behaviour)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_device_duplicate_mac(
    device_manager: DeviceManager, mock_device_storage: MagicMock
) -> None:
    """Registering the same MAC twice calls create_device twice (upsert in storage)."""
    await device_manager.register_device(
        name="First Name",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
    )
    await device_manager.register_device(
        name="Updated Name",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
    )
    assert mock_device_storage.create_device.call_count == 2


# ---------------------------------------------------------------------------
# Test-3: test_get_device_by_id
# ---------------------------------------------------------------------------


def test_get_device_by_id(
    device_manager: DeviceManager,
    mock_device_storage: MagicMock,
    sample_device_info: DeviceInfo,
) -> None:
    """get_device returns the correct DeviceInfo for a known ID."""
    mock_device_storage.get_device.return_value = sample_device_info

    result = device_manager.get_device("AA:BB:CC:DD:EE:FF")

    assert result is not None
    assert result.id == "AA:BB:CC:DD:EE:FF"
    assert result.name == "Living Room"
    mock_device_storage.get_device.assert_called_once_with("AA:BB:CC:DD:EE:FF")


# ---------------------------------------------------------------------------
# Test-4: test_get_device_not_found
# ---------------------------------------------------------------------------


def test_get_device_not_found(
    device_manager: DeviceManager, mock_device_storage: MagicMock
) -> None:
    """get_device returns None for an unknown device ID."""
    mock_device_storage.get_device.return_value = None

    result = device_manager.get_device("non-existent-id")

    assert result is None
    mock_device_storage.get_device.assert_called_once_with("non-existent-id")


# ---------------------------------------------------------------------------
# Test-5: test_list_devices
# ---------------------------------------------------------------------------


def test_list_devices(
    device_manager: DeviceManager,
    mock_device_storage: MagicMock,
    sample_device_info: DeviceInfo,
) -> None:
    """get_devices returns list of active devices."""
    mock_device_storage.get_devices.return_value = [sample_device_info]

    devices = device_manager.get_devices()

    assert len(devices) == 1
    assert devices[0].name == "Living Room"
    mock_device_storage.get_devices.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# Test-6: test_delete_device
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_device(
    device_manager: DeviceManager, mock_device_storage: MagicMock
) -> None:
    """delete_device calls unpair then marks device inactive via storage."""
    with patch.object(
        device_manager, "unpair_device", new_callable=AsyncMock
    ) as mock_unpair:
        mock_unpair.return_value = True

        result = await device_manager.delete_device("AA:BB:CC:DD:EE:FF")

        mock_unpair.assert_awaited_once_with("AA:BB:CC:DD:EE:FF")
        mock_device_storage.delete_device.assert_called_once_with("AA:BB:CC:DD:EE:FF")
        assert result is True


# ---------------------------------------------------------------------------
# Test-7: test_delete_nonexistent_device
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_nonexistent_device(
    device_manager: DeviceManager, mock_device_storage: MagicMock
) -> None:
    """delete_device on a non-existent device: storage returns False, unpair skips."""
    mock_device_storage.delete_device.return_value = False

    with patch.object(
        device_manager, "unpair_device", new_callable=AsyncMock
    ) as mock_unpair:
        mock_unpair.return_value = False

        result = await device_manager.delete_device("non-existent-id")

        assert result is False
        mock_unpair.assert_awaited_once_with("non-existent-id")
        mock_device_storage.delete_device.assert_called_once_with("non-existent-id")


# ---------------------------------------------------------------------------
# Test-8: test_discover_devices_returns_list
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discover_devices_returns_list(device_manager: DeviceManager) -> None:
    """discover_devices returns a list (BLE scanner mocked)."""
    mock_ble_device = MagicMock()
    mock_ble_device.name = "Tion_Breezer_S3_1234"
    mock_ble_device.address = "AA:BB:CC:DD:EE:FF"

    with patch(
        "tion_btle.domain.device_manager.device_manager.BleakScanner.discover",
        new_callable=AsyncMock,
        return_value=[mock_ble_device],
    ):
        devices = await device_manager.discover_devices()

    assert isinstance(devices, list)
    assert len(devices) == 1
    assert devices[0].name == "Tion_Breezer_S3_1234"


# ---------------------------------------------------------------------------
# Test-9: test_register_device_with_room
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_device_with_room(device_manager: DeviceManager) -> None:
    """register_device stores the room field correctly."""
    result = await device_manager.register_device(
        name="Bedroom Breezer",
        mac_address="11:22:33:44:55:66",
        model="Lite",
        room="Bedroom",
    )

    assert result.room == "Bedroom"
    assert result.type == "TionLite"


# ---------------------------------------------------------------------------
# Test-10: test_register_device_unknown_model_defaults_to_base_tion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_device_unknown_model_defaults_to_base_tion(
    device_manager: DeviceManager,
) -> None:
    """register_device with an unknown model falls back to base Tion class."""
    result = await device_manager.register_device(
        name="Unknown Device",
        mac_address="FF:FF:FF:FF:FF:FF",
        model="Unknown",
    )

    assert result is not None
    assert result.type == "Tion"
    assert result.model == "Unknown"


# ---------------------------------------------------------------------------
# Test-11: test_get_device_capabilities_s3
# ---------------------------------------------------------------------------


def test_get_device_capabilities_s3(
    device_manager: DeviceManager, mock_device_storage: MagicMock
) -> None:
    """S3 device has heater_control=True and light_control=False."""
    mock_device_storage.get_device.return_value = DeviceInfo(
        id="id1",
        name="S3 Device",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
    )

    caps = device_manager.get_device_capabilities("id1")

    assert caps["heater_control"] is True
    assert caps["light_control"] is False
    assert caps["fan_control"] is True


# ---------------------------------------------------------------------------
# Test-12: test_get_connected_devices_filters_active_and_paired
# ---------------------------------------------------------------------------


def test_get_connected_devices_filters_active_and_paired(
    device_manager: DeviceManager, mock_device_storage: MagicMock
) -> None:
    """get_connected_devices returns only devices with is_active=True and is_paired=True."""
    mock_device_storage.get_devices.return_value = [
        DeviceInfo(
            id="id1",
            name="Paired Active",
            type="TionS3",
            mac_address="AA:BB:CC:DD:EE:FF",
            model="S3",
            is_active=True,
            is_paired=True,
        ),
        DeviceInfo(
            id="id2",
            name="Active Not Paired",
            type="TionS3",
            mac_address="11:22:33:44:55:66",
            model="S3",
            is_active=True,
            is_paired=False,
        ),
        DeviceInfo(
            id="id3",
            name="Paired Not Active",
            type="TionS3",
            mac_address="AA:BB:CC:DD:EE:00",
            model="S3",
            is_active=False,
            is_paired=True,
        ),
    ]

    connected = device_manager.get_connected_devices()

    assert "id1" in connected
    assert "id2" not in connected
    assert "id3" not in connected
