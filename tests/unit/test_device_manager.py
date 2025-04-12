import asyncio
import json
import pytest
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch
from typing import List
from dataclasses import asdict

from tion_btle.device_manager import (
    DeviceManager,
    DeviceInfo,
    discover_and_register_all,
)
from bleak.backends.device import BLEDevice


@pytest.fixture
def mock_ble_device():
    device = MagicMock(spec=BLEDevice)
    device.name = "Tion_Breezer_S3_1234"
    device.address = "AA:BB:CC:DD:EE:FF"
    return device


@pytest.fixture
def device_manager(tmp_path):
    db_path = tmp_path / "test_devices.db"
    return DeviceManager(db_path=str(db_path))


@pytest.mark.asyncio
async def test_init_db(device_manager):
    """Test database initialization creates correct tables"""
    with sqlite3.connect(device_manager.db_path) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        assert "devices" in tables

        cursor = conn.execute("PRAGMA table_info(devices)")
        columns = [row[1] for row in cursor.fetchall()]
        expected_columns = [
            "id",
            "name",
            "type",
            "mac_address",
            "model",
            "is_active",
            "is_paired",
            "updated_date",
        ]
        assert all(col in columns for col in expected_columns)


@pytest.mark.asyncio
async def test_discover_devices(device_manager, mock_ble_device):
    """Test device discovery filters Tion devices correctly"""
    with patch(
        "tion_btle.device_manager.BleakScanner.discover", new_callable=AsyncMock
    ) as mock_discover:
        mock_discover.return_value = [
            mock_ble_device,
        ]

        devices = await device_manager.discover_devices()
        assert len(devices) == 1
        assert devices[0].name == mock_ble_device.name
        assert devices[0].address == mock_ble_device.address


@pytest.mark.asyncio
async def test_register_device(device_manager, mock_ble_device):
    """Test device registration creates correct DB entry"""
    device_info = await device_manager.register_device(mock_ble_device)

    assert device_info.name == "S3 1234"
    assert device_info.type == "TionS3"
    assert device_info.mac_address == mock_ble_device.address
    assert device_info.model == "S3"
    assert not device_info.is_paired

    # Check DB content
    with sqlite3.connect(device_manager.db_path) as conn:
        cursor = conn.execute("SELECT * FROM devices")
        rows = cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "S3 1234"  # name
        assert rows[0][5] == 1  # is_active


@pytest.mark.asyncio
async def test_get_devices(device_manager, mock_ble_device):
    """Test retrieving registered devices"""
    # Register a device
    await device_manager.register_device(mock_ble_device)

    devices = device_manager.get_devices()
    assert len(devices) == 1
    assert isinstance(devices[0], DeviceInfo)
    assert devices[0].name == "S3 1234"


@pytest.mark.asyncio
async def test_get_device(device_manager, mock_ble_device):
    """Test retrieving single device by ID"""
    device_info = await device_manager.register_device(mock_ble_device)
    retrieved = device_manager.get_device(device_info.id)

    assert retrieved is not None
    assert asdict(retrieved) == asdict(device_info)


@pytest.mark.asyncio
async def test_update_device(device_manager, mock_ble_device):
    """Test updating device properties"""
    device_info = await device_manager.register_device(mock_ble_device)

    # Update name and active status
    updated = device_manager.update_device(
        device_info.id, name="New Name", is_active=False
    )

    assert updated
    retrieved = device_manager.get_device(device_info.id)
    assert retrieved.name == "New Name"
    assert not retrieved.is_active


@pytest.mark.asyncio
async def test_pair_device(device_manager, mock_ble_device):
    """Test device pairing flow"""
    device_info = await device_manager.register_device(mock_ble_device)

    with patch("tion_btle.TionS3.pair", new_callable=AsyncMock) as mock_pair:
        # Successful pairing
        mock_pair.return_value = None
        paired = await device_manager.pair_device(device_info.id)

        assert paired
        retrieved = device_manager.get_device(device_info.id)
        assert retrieved.is_paired

        # Failed pairing
        mock_pair.side_effect = Exception("Pairing failed")
        paired = await device_manager.pair_device(device_info.id)
        assert not paired


@pytest.mark.asyncio
async def test_unpair_device(device_manager, mock_ble_device):
    """Test device unpairing flow"""
    device_info = await device_manager.register_device(mock_ble_device)
    devices = device_manager.get_devices()
    assert len(devices) == 1

    # First pair the device
    with patch("tion_btle.TionS3.pair", new_callable=AsyncMock):
        paired = await device_manager.pair_device(device_info.id)
        assert paired

    # Then unpair
    with patch("tion_btle.TionS3._btle", new_callable=AsyncMock):
        with patch(
            "bleak.BleakClient.unpair", new_callable=AsyncMock
        ) as mock_ble_unpair:
            mock_ble_unpair.return_value = True
            unpaired = await device_manager.unpair_device(device_info.id)

            assert unpaired
            retrieved = device_manager.get_device(device_info.id)
            assert not retrieved.is_paired


@pytest.mark.asyncio
async def test_delete_device(device_manager, mock_ble_device):
    """Test device deletion (marking as inactive)"""
    device_info = await device_manager.register_device(mock_ble_device)
    devices = device_manager.get_devices()
    assert len(devices) == 1

    with patch(
        "tion_btle.device_manager.DeviceManager.unpair_device", new_callable=AsyncMock
    ) as mock_unpair:
        mock_unpair.return_value = True
        deleted = await device_manager.delete_device(device_info.id)

        assert deleted
        devices = device_manager.get_devices()
        assert len(devices) == 0  # active_only=True by default

        # Check inactive devices
        devices = device_manager.get_devices(active_only=False)
        assert len(devices) == 1
        assert not devices[0].is_active


@pytest.mark.asyncio
async def test_discover_and_register_all(device_manager, mock_ble_device):
    """Test batch discovery and registration"""
    with patch(
        "tion_btle.device_manager.BleakScanner.discover", new_callable=AsyncMock
    ) as mock_discover:
        mock_discover.return_value = [mock_ble_device]

        with patch(
            "tion_btle.device_manager.DeviceManager.register_device",
            new_callable=AsyncMock,
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
            assert registered[0].name == "Test Device"

# Device Groups Tests
async def test_create_device_group(device_manager, mock_ble_device):
    """Test creating a device group"""
    await device_manager.register_device(mock_ble_device)
    device_id = mock_ble_device.address
        
    group_id = device_manager.create_device_group(
        name="Living Room", 
        device_ids=[device_id]
    )
    assert group_id > 0
        
    groups = device_manager.get_device_groups()
    assert len(groups) == 1
    assert groups[0]["name"] == "Living Room"
    assert device_id in json.loads(groups[0]["device_ids"])

async def test_update_device_group(device_manager, mock_ble_device):
    """Test updating a device group"""
    await device_manager.register_device(mock_ble_device)
    device_id = mock_ble_device.address
    group_id = device_manager.create_device_group(
        name="Original Name",
        device_ids=[device_id]
    )
        
    updated = device_manager.update_device_group(
        group_id,
        name="Updated Name",
        device_ids=[device_id, "test-device"]
    )
    assert updated
        
    groups = device_manager.get_device_groups()
    assert groups[0]["name"] == "Updated Name"
    assert len(json.loads(groups[0]["device_ids"])) == 2

async def test_delete_device_group(device_manager, mock_ble_device):
    """Test deleting a device group"""
    await device_manager.register_device(mock_ble_device)
    group_id = device_manager.create_device_group(
        name="Test Group",
        device_ids=[mock_ble_device.address]
    )
        
    deleted = device_manager.delete_device_group(group_id)
    assert deleted
        
    groups = device_manager.get_device_groups()
    assert len(groups) == 0
        
    all_groups = device_manager.get_device_groups(active_only=False)
    assert len(all_groups) == 1
    assert not all_groups[0]["is_active"]
