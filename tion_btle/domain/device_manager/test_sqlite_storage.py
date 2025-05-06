import pytest
import sqlite3
import json
from pathlib import Path
from typing import List

from tion_btle.domain.device_manager.models import DeviceInfo, DeviceGroup
from tion_btle.domain.device_manager.sqlite_storage import SQLiteDeviceStorage


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
        model="S3"
    )
    
    # Create device
    assert storage.create_device(device) is True
    
    # Get device
    retrieved = storage.get_device("test-id")
    assert retrieved is not None
    assert retrieved.name == "Test Device"
    assert retrieved.is_active is True


def test_update_device(storage):
    """Test device updates"""
    device = DeviceInfo(
        id="test-id",
        name="Test Device",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3"
    )
    storage.create_device(device)
    
    # Update device
    assert storage.update_device(
        "test-id",
        name="Updated Name",
        room="Living Room",
        is_paired=True
    ) is True
    
    # Verify update
    updated = storage.get_device("test-id")
    assert updated.name == "Updated Name"
    assert updated.room == "Living Room"
    assert updated.is_paired is True


def test_delete_device(storage):
    """Test device deletion (marking as inactive)"""
    device = DeviceInfo(
        id="test-id",
        name="Test Device",
        type="TionS3",
        mac_address="AA:BB:CC:DD:EE:FF",
        model="S3"
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
    assert all_devices[0].is_active is False


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
    assert storage.update_group(
        group_id,
        name="Updated Group",
        device_ids=["dev1", "dev2"]
    ) is True
    
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
