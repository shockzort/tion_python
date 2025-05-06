import sqlite3
import json
from typing import List, Dict, Optional, Any
from .models import DeviceInfo, DeviceGroup
from .interfaces import IDeviceStorage, IDeviceGroupStorage

class SQLiteDeviceStorage(IDeviceStorage, IDeviceGroupStorage):
    """SQLite implementation of device storage interfaces"""
    
    def __init__(self, db_path: str = "devices.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
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
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS device_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    device_ids TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get_devices(self, active_only: bool = True) -> List[DeviceInfo]:
        query = "SELECT id, name, type, mac_address, model, is_active, is_paired, room FROM devices"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY name"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query)
            return [DeviceInfo(*row) for row in cursor.fetchall()]

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT id, name, type, mac_address, model, is_active, is_paired, room
                FROM devices WHERE id = ?
            """, (device_id,))
            row = cursor.fetchone()
            return DeviceInfo(*row) if row else None

    def create_device(self, device: DeviceInfo) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT INTO devices (id, name, type, mac_address, model, is_paired)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(mac_address) DO UPDATE SET
                    name=excluded.name,
                    type=excluded.type,
                    model=excluded.model,
                    updated_date=CURRENT_TIMESTAMP,
                    is_active=1
            """, (
                device.id, device.name, device.type, 
                device.mac_address, device.model, False
            ))
            conn.commit()
            return True

    def update_device(self, device_id: str, **kwargs) -> bool:
        valid_fields = {
            "name", "type", "mac_address", "model", 
            "is_active", "is_paired", "room"
        }
        updates = {k: v for k, v in kwargs.items() if k in valid_fields}
        if not updates:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [device_id]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"""
                UPDATE devices
                SET {set_clause}, updated_date = CURRENT_TIMESTAMP
                WHERE id = ?
            """, params)
            conn.commit()
            return conn.total_changes > 0

    def delete_device(self, device_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE devices
                SET is_active = 0, updated_date = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (device_id,))
            conn.commit()
            return conn.total_changes > 0

    def get_groups(self, active_only: bool = True) -> List[DeviceGroup]:
        query = "SELECT id, name, device_ids, is_active FROM device_groups"
        if active_only:
            query += " WHERE is_active = 1"

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query)
            return [
                DeviceGroup(
                    id=row[0],
                    name=row[1],
                    device_ids=json.loads(row[2]),
                    is_active=bool(row[3])
                ) for row in cursor.fetchall()
            ]

    def create_group(self, name: str, device_ids: List[str]) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                INSERT INTO device_groups (name, device_ids)
                VALUES (?, ?)
                RETURNING id
            """, (name, json.dumps(device_ids)))
            group_id = cursor.fetchone()[0]
            conn.commit()
            return group_id

    def update_group(self, group_id: int, **kwargs) -> bool:
        valid_fields = {"name", "device_ids", "is_active"}
        updates = {k: v for k, v in kwargs.items() if k in valid_fields}
        if not updates:
            return False

        if "device_ids" in updates:
            updates["device_ids"] = json.dumps(updates["device_ids"])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [group_id]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"""
                UPDATE device_groups
                SET {set_clause}
                WHERE id = ?
            """, params)
            conn.commit()
            return conn.total_changes > 0

    def delete_group(self, group_id: int) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE device_groups
                SET is_active = 0
                WHERE id = ?
            """, (group_id,))
            conn.commit()
            return conn.total_changes > 0
