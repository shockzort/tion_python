import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List
from dataclasses import asdict

from tion_btle.domain.device_manager.device_manager import DeviceManager, discover_and_register_all
from tion_btle.domain.device_manager.models import DeviceInfo, DeviceGroup
from tion_btle.domain.device_manager.interfaces import IDeviceStorage, IDeviceGroupStorage
from tion_btle import Tion, TionS3, TionLite, TionS4
from bleak.backends.device import BLEDevice


@pytest.fixture
def mock_device_storage():
    storage = MagicMock(spec=IDeviceStorage)
    storage.get_devices.return_value = []
    storage.get_device.return_value = None
    storage.create_device.return_value = True
    storage.update_device.return_value = True
    storage.delete_device.return_value = True
    return storage


@pytest.fixture
def mock_group_storage():
    storage = MagicMock(spec=IDeviceGroupStorage)
    storage.get_groups.return_value = []
    storage.create_group.return_value = 1
    storage.update_group.return_value = True
    storage.delete_group.return_value = True
    return storage


@pytest.fixture
def device_manager(mock_device_storage, mock_group_storage):
    return DeviceManager(mock_device_storage, mock_group_storage)


@pytest.fixture
def mock_ble_device():
    device = MagicMock(spec=BLEDevice)
    device.name = "Tion_Breezer_S3_1234"
    device.address = "AA:BB:CC:DD:EE:FF"
    return device


@pytest.mark.asyncio
async def test_discover_devices(device_manager, mock_ble_device):
    """Test device discovery filters Tion devices correctly"""
    with patch(
        "tion_btle.domain.device_manager.device_manager.BleakScanner.discover",
        new_callable=AsyncMock
    ) as mock_discover:
        mock_discover.return_value = [mock_ble_device]
        devices = await device_manager.discover_devices()
        assert len(devices) == 1
        assert devices[0].name == mock_ble_device.name


def test_get_device_class(device_manager):
    """Test device class detection"""
    assert device_manager.get_device_class("Tion_Breezer_S3") == TionS3
    assert device_manager.get_device_class("Tion_Breezer_Lite") == TionLite
    assert device_manager.get_device_class("Tion_Breezer_S4") == TionS4
    assert device_manager.get_device_class("Unknown") == Tion


@pytest.mark.asyncio
async def test_register_device(device_manager, mock_ble_device, mock_device_storage):
    """Test device registration"""
    device_info = await device_manager.register_device(mock_ble_device)

    assert device_info.name == "S3 1234"
    assert device_info.type == "TionS3"
    mock_device_storage.create_device.assert_called_once()


@pytest.mark.asyncio
async def test_register_device_with_auto_pair(device_manager, mock_ble_device):
    """Test device registration with auto-pairing"""
    with patch(
        "tion_btle.domain.device_manager.device_manager.DeviceManager.pair_device",
        new_callable=AsyncMock
    ) as mock_pair:
        await device_manager.register_device(mock_ble_device, auto_pair=True)
        mock_pair.assert_called_once()


def test_get_devices(device_manager, mock_device_storage):
    """Test getting all devices"""
    mock_devices = [
        DeviceInfo(
            id="1", name="Device 1", type="TionS3",
            mac_address="AA:BB:CC:DD:EE:FF", model="S3"
        )
    ]
    mock_device_storage.get_devices.return_value = mock_devices

    devices = device_manager.get_devices()
    assert len(devices) == 1
    assert devices[0].name == "Device 1"


def test_get_connected_devices(device_manager, mock_device_storage):
    """Test getting connected devices"""
    mock_devices = [
        DeviceInfo(
            id="1", name="Device 1", type="TionS3",
            mac_address="AA:BB:CC:DD:EE:FF", model="S3",
            is_active=True, is_paired=True
        ),
        DeviceInfo(
            id="2", name="Device 2", type="TionS3",
            mac_address="BB:BB:CC:DD:EE:FF", model="S3",
            is_active=True, is_paired=False
        )
    ]
    mock_device_storage.get_devices.return_value = mock_devices

    connected = device_manager.get_connected_devices()
    assert len(connected) == 1
    assert "1" in connected


def test_get_device_capabilities(device_manager, mock_device_storage):
    """Test device capabilities detection"""
    test_cases = [
        ("TionS3", {
            "fan_control": True,
            "heater_control": True,
            "temperature_control": True,
            "light_control": False,
            "mode_control": False
        }),
        ("TionLite", {
            "fan_control": True,
            "heater_control": False,
            "temperature_control": False,
            "light_control": True,
            "mode_control": False
        }),
        ("TionS4", {
            "fan_control": True,
            "heater_control": True,
            "temperature_control": True,
            "light_control": False,
            "mode_control": True
        })
    ]

    for device_type, expected in test_cases:
        mock_device_storage.get_device.return_value = DeviceInfo(
            id="1", name="Test", type=device_type,
            mac_address="AA:BB:CC:DD:EE:FF", model=device_type.replace("Tion", "")
        )
        caps = device_manager.get_device_capabilities("1")
        assert caps == expected


@pytest.mark.asyncio
async def test_pair_device_success(device_manager, mock_device_storage):
    """Test successful device pairing"""
    mock_device_storage.get_device.return_value = DeviceInfo(
        id="1", name="Test", type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF", model="S3"
    )

    with patch("tion_btle.TionS3.pair", new_callable=AsyncMock) as mock_pair:
        result = await device_manager.pair_device("1")
        assert result is True
        mock_device_storage.update_device.assert_called_once_with(
            "1", is_paired=True
        )


@pytest.mark.asyncio
async def test_pair_device_failure(device_manager, mock_device_storage):
    """Test failed device pairing"""
    mock_device_storage.get_device.return_value = DeviceInfo(
        id="1", name="Test", type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF", model="S3"
    )

    with patch("tion_btle.TionS3.pair", new_callable=AsyncMock) as mock_pair:
        mock_pair.side_effect = Exception("Pairing failed")
        result = await device_manager.pair_device("1")
        assert result is False


@pytest.mark.asyncio
async def test_unpair_device(device_manager, mock_device_storage):
    """Test device unpairing"""
    mock_device_storage.get_device.return_value = DeviceInfo(
        id="1", name="Test", type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF", model="S3",
        is_paired=True
    )

    with patch("tion_btle.TionS3._btle.unpair", new_callable=AsyncMock) as mock_unpair:
        result = await device_manager.unpair_device("1")
        assert result is True
        mock_device_storage.update_device.assert_called_once_with(
            "1", is_paired=False
        )


def test_device_groups_operations(device_manager, mock_group_storage):
    """Test device group operations"""
    # Create group
    group_id = device_manager.create_device_group("Test Group", ["1", "2"])
    assert group_id == 1
    mock_group_storage.create_group.assert_called_once_with("Test Group", ["1", "2"])

    # Update group
    device_manager.update_device_group(1, name="Updated Group")
    mock_group_storage.update_group.assert_called_once_with(1, name="Updated Group")

    # Delete group
    device_manager.delete_device_group(1)
    mock_group_storage.delete_group.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_discover_and_register_all(device_manager, mock_ble_device):
    """Test batch discovery and registration"""
    with patch(
        "tion_btle.domain.device_manager.device_manager.DeviceManager.discover_devices",
        new_callable=AsyncMock
    ) as mock_discover:
        mock_discover.return_value = [mock_ble_device]

        with patch(
            "tion_btle.domain.device_manager.device_manager.DeviceManager.register_device",
            new_callable=AsyncMock
        ) as mock_register:
            mock_register.return_value = DeviceInfo(
                id=mock_ble_device.address,
                name="Test Device",
                type="TionS3",
                mac_address=mock_ble_device.address,
                model="S3",
            )

            registered = await discover_and_register_all(device_manager)
            assert len(registered) == 1
