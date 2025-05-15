import pytest
import sqlite3
import json
from pathlib import Path
from typing import List, Dict
from unittest.mock import patch

from tion_btle.domain.device_manager.models import DeviceInfo, DeviceGroup
from tion_btle.domain.device_manager.sqlite_storage import SQLiteDeviceStorage
from tion_btle.domain.device_manager.interfaces import (
    IDeviceStorage,
    IDeviceGroupStorage,
)


@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test.db"
    yield str(db_path)
    if Path(db_path).exists():
        Path(db_path).unlink()


@pytest.fixture
def storage(temp_db):
    return SQLiteDeviceStorage(temp_db)


def test_init_db(storage, temp_db):
    """Test database initialization creates correct tables"""
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        assert "devices" in tables
        assert "device_groups" in tables


def test_create_and_get_device(storage):
    """Test device creation and retrieval"""
    device = DeviceInfo(
        id="test-id",
        name="Test Device",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
    )

    # Create device
    assert storage.create_device(device) is True

    # Get device
    retrieved = storage.get_device("test-id")
    assert retrieved is not None
    assert retrieved.name == "Test Device"
    assert bool(retrieved.is_active) is True


def test_update_device(storage):
    """Test device updates"""
    device = DeviceInfo(
        id="test-id",
        name="Test Device",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
    )
    storage.create_device(device)

    # Update device
    assert (
        storage.update_device(
            "test-id", name="Updated Name", room="Living Room", is_paired=True
        )
        is True
    )

    # Verify update
    updated = storage.get_device("test-id")
    assert updated.name == "Updated Name"
    assert updated.room == "Living Room"
    assert bool(updated.is_paired) is True


def test_delete_device(storage):
    """Test device deletion (marking as inactive)"""
    device = DeviceInfo(
        id="test-id",
        name="Test Device",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
    )
    storage.create_device(device)

    # Delete device
    assert storage.delete_device("test-id") is True

    # Verify inactive
    devices = storage.get_devices(active_only=True)
    assert len(devices) == 0

    # Verify still exists when inactive
    all_devices = storage.get_devices(active_only=False)
    assert len(all_devices) == 1
    assert bool(all_devices[0].is_active) is False


def test_create_and_get_group(storage):
    """Test group creation and retrieval"""
    group_id = storage.create_group("Test Group", ["dev1", "dev2"])
    assert group_id > 0

    groups = storage.get_groups()
    assert len(groups) == 1
    assert groups[0].name == "Test Group"
    assert groups[0].device_ids == ["dev1", "dev2"]


def test_update_group(storage):
    """Test group updates"""
    group_id = storage.create_group("Test Group", ["dev1"])

    # Update group
    assert (
        storage.update_group(
            group_id, name="Updated Group", device_ids=["dev1", "dev2"]
        )
        is True
    )

    # Verify update
    groups = storage.get_groups()
    assert groups[0].name == "Updated Group"
    assert groups[0].device_ids == ["dev1", "dev2"]


def test_delete_group(storage):
    """Test group deletion (marking as inactive)"""
    group_id = storage.create_group("Test Group", ["dev1"])

    # Delete group
    assert storage.delete_group(group_id) is True

    # Verify inactive
    groups = storage.get_groups(active_only=True)
    assert len(groups) == 0

    # Verify still exists when inactive
    all_groups = storage.get_groups(active_only=False)
    assert len(all_groups) == 1
    assert all_groups[0].is_active is False


def test_delete_nonexistent_group(storage):
    """Test deleting a group that doesn't exist"""
    # Try to delete a non-existent group
    assert storage.delete_group(999) is False


def test_update_nonexistent_group(storage):
    """Test updating a group that doesn't exist"""
    # Try to update a non-existent group
    assert storage.update_group(999, name="New Name") is False


def test_update_device_nonexistent(storage):
    """Test updating a device that doesn't exist"""
    # Try to update a non-existent device
    assert storage.update_device("non-existent", name="New Name") is False


def test_delete_device_nonexistent(storage):
    """Test deleting a device that doesn't exist"""
    # Try to delete a non-existent device
    assert storage.delete_device("non-existent") is False


def test_get_device_nonexistent(storage):
    """Test getting a device that doesn't exist"""
    # Try to get a non-existent device
    assert storage.get_device("non-existent") is None


def test_update_device_invalid_fields(storage):
    """Test updating a device with invalid fields"""
    # Create a device first
    device = DeviceInfo(
        id="test-id",
        name="Test Device",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
    )
    storage.create_device(device)

    # Try to update with invalid fields
    assert storage.update_device("test-id", invalid_field="Invalid Value") is False

    # Verify device wasn't changed
    updated = storage.get_device("test-id")
    assert updated.name == "Test Device"


def test_update_group_invalid_fields(storage):
    """Test updating a group with invalid fields"""
    # Create a group first
    group_id = storage.create_group("Test Group", ["dev1"])

    # Try to update with invalid fields
    assert storage.update_group(group_id, invalid_field="Invalid Value") is False


def test_create_device_duplicate_mac(storage):
    """Test creating a device with a duplicate MAC address"""
    # Create first device
    device1 = DeviceInfo(
        id="test-id-1",
        name="Test Device 1",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3",
    )
    storage.create_device(device1)

    # Create second device with same MAC
    device2 = DeviceInfo(
        id="test-id-2",
        name="Test Device 2",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",  # Same MAC
        model="S3",
    )
    storage.create_device(device2)

    # Verify the first device was updated, not duplicated
    devices = storage.get_devices(active_only=False)
    assert len(devices) == 1
    assert devices[0].name == "Test Device 2"  # Updated name
    assert devices[0].id == "test-id-2"  # Updated ID


def test_interface_compliance():
    """Test that SQLiteDeviceStorage properly implements the interfaces"""
    storage = SQLiteDeviceStorage(":memory:")
    assert isinstance(storage, IDeviceStorage)
    assert isinstance(storage, IDeviceGroupStorage)

    # Verify all interface methods are implemented
    for method_name in [
        "get_devices",
        "get_device",
        "create_device",
        "update_device",
        "delete_device",
        "get_groups",
        "create_group",
        "update_group",
        "delete_group",
    ]:
        assert hasattr(storage, method_name)
        assert callable(getattr(storage, method_name))


def test_db_connection_error():
    """Test handling of database connection errors"""
    with patch("sqlite3.connect", side_effect=sqlite3.Error("Connection error")):
        # Should not raise exception but handle gracefully
        storage = SQLiteDeviceStorage(":memory:")

        # Operations should fail gracefully
        assert storage.get_devices() == []
        assert storage.get_device("any-id") is None
