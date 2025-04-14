import asyncio
import logging
from typing import List, Dict, Optional
from dataclasses import dataclass
import sqlite3
import json
from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from tion_btle import Tion, TionS3, TionLite, TionS4

_LOGGER = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    """Dataclass for storing device information"""

    id: str
    name: str
    type: str
    mac_address: str
    model: str
    is_active: bool = True
    is_paired: bool = False
    room: Optional[str] = None


class DeviceManager:
    """Manager for Tion devices discovery and registration"""

    TION_DEVICE_PREFIXES = ("Tion_Breezer_", "tion_")

    def __init__(self, db_path: str = "devices.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            # Devices table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    mac_address TEXT UNIQUE NOT NULL,
                    model TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    is_paired BOOLEAN DEFAULT 0,
                    room TEXT,
                    updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )

            # Groups table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    device_ids TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )
            conn.commit()

    async def discover_devices(self) -> List[BLEDevice]:
        """Discover Tion BLE devices in range"""
        devices = await BleakScanner.discover()
        return [
            d
            for d in devices
            if d.name and d.name.startswith(self.TION_DEVICE_PREFIXES)
        ]

    def get_device_class(self, device_name: str) -> type[Tion]:
        """Get appropriate Tion class based on device name"""
        if "S3" in device_name:
            return TionS3
        elif "Lite" in device_name:
            return TionLite
        elif "S4" in device_name:
            return TionS4
        return Tion

    async def register_device(
        self, device: BLEDevice, name: str = None, auto_pair: bool = False
    ) -> DeviceInfo:
        """Register new device in database"""
        device_class = self.get_device_class(device.name)
        device_type = device_class.__name__

        if not name:
            name = device.name.replace("Tion_Breezer_", "").replace("_", " ").title()

        device_info = DeviceInfo(
            id=device.address,
            name=name,
            type=device_type,
            mac_address=device.address,
            model=device_class.__name__.replace("Tion", ""),
        )

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO devices (id, name, type, mac_address, model, is_paired)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(mac_address) DO UPDATE SET
                    name=excluded.name,
                    type=excluded.type,
                    model=excluded.model,
                    updated_date=CURRENT_TIMESTAMP,
                    is_active=1
            """,
                (
                    device_info.id,
                    device_info.name,
                    device_info.type,
                    device_info.mac_address,
                    device_info.model,
                    False,
                ),
            )

            if auto_pair:
                await self.pair_device(device_info.id)
            conn.commit()

        return device_info

    def get_devices(self, active_only: bool = True) -> List[DeviceInfo]:
        """Get list of registered devices"""
        query = """
            SELECT id, name, type, mac_address, model, is_active, is_paired, room
            FROM devices
        """
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY name"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query)
            return [DeviceInfo(*row) for row in cursor.fetchall()]

    def get_connected_devices(self) -> Dict[str, DeviceInfo]:
        """Get dictionary of currently connected devices {id: DeviceInfo}"""
        devices = self.get_devices()
        return {d.id: d for d in devices if d.is_active and d.is_paired}

    def get_device_capabilities(self, device_id: str) -> Dict[str, bool]:
        """Get device capabilities based on its type"""
        device = self.get_device(device_id)
        if not device:
            return {}

        capabilities = {
            "fan_control": True,
            "heater_control": "S3" in device.type or "S4" in device.type,
            "temperature_control": "S3" in device.type or "S4" in device.type,
            "light_control": "Lite" in device.type,
            "mode_control": "S4" in device.type,
        }
        return capabilities

    def get_device_groups(self, active_only: bool = True) -> List[Dict]:
        """Get list of device groups"""
        query = "SELECT id, name, device_ids, is_active FROM device_groups"
        if active_only:
            query += " WHERE is_active = 1"

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(query)
            return [dict(row) for row in cursor.fetchall()]

    def create_device_group(self, name: str, device_ids: List[str]) -> int:
        """Create new device group"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO device_groups (name, device_ids)
                VALUES (?, ?)
                RETURNING id
                """,
                (name, json.dumps(device_ids)),
            )
            group_id = cursor.fetchone()[0]
            conn.commit()
            return group_id

    def update_device_group(self, group_id: int, **kwargs) -> bool:
        """Update device group properties"""
        valid_fields = {"name", "device_ids", "is_active"}
        updates = {k: v for k, v in kwargs.items() if k in valid_fields}

        if not updates:
            return False

        if "device_ids" in updates:
            updates["device_ids"] = json.dumps(updates["device_ids"])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [group_id]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                UPDATE device_groups
                SET {set_clause}
                WHERE id = ?
                """,
                params,
            )
            conn.commit()
            return conn.total_changes > 0

    def delete_device_group(self, group_id: int) -> bool:
        """Mark device group as inactive"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE device_groups
                SET is_active = 0
                WHERE id = ?
                """,
                (group_id,),
            )
            conn.commit()
            return conn.total_changes > 0

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Get single device by ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT id, name, type, mac_address, model, is_active, is_paired, room
                FROM devices
                WHERE id = ?
            """,
                (device_id,),
            )
            row = cursor.fetchone()
            return DeviceInfo(*row) if row else None

    def update_device(self, device_id: str, **kwargs) -> bool:
        """Update device properties"""
        valid_fields = {
            "name",
            "type",
            "mac_address",
            "model",
            "is_active",
            "is_paired",
            "room",
        }
        updates = {k: v for k, v in kwargs.items() if k in valid_fields}

        if not updates:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [device_id]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                UPDATE devices
                SET {set_clause}, updated_date = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                params,
            )
            conn.commit()
            return conn.total_changes > 0

    async def delete_device(self, device_id: str) -> bool:
        """Mark device as inactive and unpair it"""
        # First unpair the device
        await self.unpair_device(device_id)

        # Then mark as inactive
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE devices
                SET is_active = 0, updated_date = CURRENT_TIMESTAMP
                WHERE id = ?
            """,
                (device_id,),
            )
            conn.commit()
            return conn.total_changes > 0

    async def pair_device(self, device_id: str, timeout: int = 30) -> bool:
        """Pair with device using Tion's pair() method"""
        device_info = self.get_device(device_id)
        if not device_info:
            raise ValueError(f"Device {device_id} not found")

        device_class = self.get_device_class(device_info.name)
        device = device_class(device_info.mac_address)

        try:
            _LOGGER.info(
                f"Starting pairing process for {device_id}, timeout: {timeout}s"
            )
            await asyncio.wait_for(device.pair(), timeout=timeout)

            # Save pairing success
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    UPDATE devices
                    SET is_paired = 1, updated_date = CURRENT_TIMESTAMP
                    WHERE id = ?
                """,
                    (device_id,),
                )
                conn.commit()

            _LOGGER.info(f"Successfully paired device {device_id}")
            return True

        except asyncio.TimeoutError:
            _LOGGER.error(f"Pairing timeout for device {device_id}")
            return False
        except Exception as e:
            _LOGGER.error(f"Failed to pair device {device_id}: {str(e)}")
            return False

    async def unpair_device(self, device_id: str) -> bool:
        """Unpair device"""
        device_info = self.get_device(device_id)
        if not device_info or not device_info.is_paired:
            return False

        device_class = self.get_device_class(device_info.type)
        device = device_class(device_info.mac_address)

        try:
            await device._btle.unpair()

            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    UPDATE devices
                    SET is_paired = 0, updated_date = CURRENT_TIMESTAMP
                    WHERE id = ?
                """,
                    (device_id,),
                )
                conn.commit()

            _LOGGER.info(f"Successfully unpaired device {device_id}")
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to unpair device {device_id}: {str(e)}")
            return False


async def discover_and_register_all(manager: DeviceManager) -> List[DeviceInfo]:
    """Discover and register all Tion devices in range"""
    devices = await manager.discover_devices()
    registered = []

    for device in devices:
        try:
            device_info = await manager.register_device(device)
            registered.append(device_info)
            _LOGGER.info(f"Registered device: {device_info}")
        except Exception as e:
            _LOGGER.error(f"Failed to register device {device}: {e}")

    return registered
