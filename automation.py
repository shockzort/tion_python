import sqlite3
import json
from typing import List, Optional
from dataclasses import dataclass
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

class AutomationManager:
    def __init__(self, db_path: str = "devices.db"):
        self.db_path = db_path
    
    def create_scenario(self, scenario: Scenario) -> int:
        """Create new automation scenario"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO scenarios 
                (name, trigger_type, trigger_params, action_params, is_active)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    scenario.name,
                    scenario.trigger_type,
                    json.dumps(scenario.trigger_params),
                    json.dumps(scenario.action_params),
                    scenario.is_active
                )
            )
            conn.commit()
            return cursor.lastrowid
    
    def get_scenarios(self, active_only: bool = True) -> List[Scenario]:
        """Get all scenarios"""
        query = "SELECT id, name, trigger_type, trigger_params, action_params, is_active, created_at FROM scenarios"
        if active_only:
            query += " WHERE is_active = 1"
            
        scenarios = []
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(query)
            for row in cursor.fetchall():
                scenarios.append(Scenario(
                    id=row[0],
                    name=row[1],
                    trigger_type=row[2],
                    trigger_params=json.loads(row[3]),
                    action_params=json.loads(row[4]),
                    is_active=bool(row[5]),
                    created_at=datetime.fromisoformat(row[6]) if row[6] else None
                ))
        return scenarios
    
    def run_scenario(self, scenario_id: int) -> bool:
        """Execute scenario actions"""
        scenario = self.get_scenario(scenario_id)
        if not scenario:
            return False
            
        # TODO: Implement actual device control
        print(f"Running scenario {scenario.name}")
        return True
    
    def get_scenario(self, scenario_id: int) -> Optional[Scenario]:
        """Get single scenario by ID"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT id, name, trigger_type, trigger_params, action_params, is_active, created_at "
                "FROM scenarios WHERE id = ?",
                (scenario_id,)
            )
            row = cursor.fetchone()
            if row:
                return Scenario(
                    id=row[0],
                    name=row[1],
                    trigger_type=row[2],
                    trigger_params=json.loads(row[3]),
                    action_params=json.loads(row[4]),
                    is_active=bool(row[5]),
                    created_at=datetime.fromisoformat(row[6]) if row[6] else None
                )
        return None
