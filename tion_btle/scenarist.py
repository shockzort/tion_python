import json
import sqlite3
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
from datetime import datetime


@dataclass
class Scenario:
    id: int
    name: str
    trigger_type: str  # 'time' or 'sensor'
    trigger_params: dict
    action_params: dict
    is_active: bool = True
    created_at: datetime = None
    last_executed: Optional[datetime] = None
    execution_count: int = 0
    last_status: Optional[bool] = None  # True=success, False=failure


class Scenarist:
    def __init__(self, db_path: str = "devices.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize scenarios table"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scenarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    trigger_params TEXT NOT NULL,
                    action_params TEXT NOT NULL,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )
            conn.commit()

    def create_scenario(self, scenario: Scenario) -> int:
        """Create new scenario"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO scenarios (name, trigger_type, trigger_params, action_params)
                VALUES (?, ?, ?, ?)
                RETURNING id
                """,
                (
                    scenario.name,
                    scenario.trigger_type,
                    json.dumps(scenario.trigger_params),
                    json.dumps(scenario.action_params),
                ),
            )
            scenario_id = cursor.fetchone()[0]
            conn.commit()
            return scenario_id

    def get_scenarios(self, active_only: bool = True) -> List[Scenario]:
        """Get list of scenarios"""
        query = """
            SELECT id, name, trigger_type, trigger_params, action_params, is_active, created_at
            FROM scenarios
        """
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY created_at DESC"

        scenarios = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query)
            for row in cursor.fetchall():
                scenarios.append(
                    Scenario(
                        id=row[0],
                        name=row[1],
                        trigger_type=row[2],
                        trigger_params=json.loads(row[3]),
                        action_params=json.loads(row[4]),
                        is_active=bool(row[5]),
                        created_at=row[6],
                    )
                )
        return scenarios

    def get_scenarios_for_device(self, device_id: str) -> List[Scenario]:
        """Get scenarios targeting a specific device"""
        scenarios = self.get_scenarios()
        return [
            s for s in scenarios 
            if s.action_params.get('device_id') == device_id
        ]

    def validate_action_params(self, action_params: dict) -> bool:
        """Validate scenario action parameters structure"""
        required = ['device_id', 'command']
        if not all(k in action_params for k in required):
            return False
            
        valid_commands = ['turn_on', 'turn_off', 'set_speed', 'set_temp', 'set_mode']
        if action_params['command'] not in valid_commands:
            return False
            
        return True

    def get_scenario(self, scenario_id: int) -> Optional[Scenario]:
        """Get single scenario by ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                """
                SELECT id, name, trigger_type, trigger_params, action_params, is_active, created_at
                FROM scenarios
                WHERE id = ?
                """,
                (scenario_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return Scenario(
                id=row[0],
                name=row[1],
                trigger_type=row[2],
                trigger_params=json.loads(row[3]),
                action_params=json.loads(row[4]),
                is_active=bool(row[5]),
                created_at=row[6],
            )

    def update_scenario(self, scenario_id: int, **kwargs) -> bool:
        """Update scenario properties"""
        valid_fields = {
            "name",
            "trigger_type",
            "trigger_params",
            "action_params",
            "is_active",
        }
        updates = {k: v for k, v in kwargs.items() if k in valid_fields}

        if not updates:
            return False

        if "trigger_params" in updates:
            updates["trigger_params"] = json.dumps(updates["trigger_params"])
        if "action_params" in updates:
            updates["action_params"] = json.dumps(updates["action_params"])

        set_clause = ", ".join(f"{k} = ?" for k in updates)
        params = list(updates.values()) + [scenario_id]

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                f"""
                UPDATE scenarios
                SET {set_clause}
                WHERE id = ?
                """,
                params,
            )
            conn.commit()
            return conn.total_changes > 0

    def delete_scenario(self, scenario_id: int) -> bool:
        """Mark scenario as inactive"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE scenarios
                SET is_active = 0
                WHERE id = ?
                """,
                (scenario_id,),
            )
            conn.commit()
            return conn.total_changes > 0
