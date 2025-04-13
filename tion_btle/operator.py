import asyncio
import logging
from typing import List, Dict, Optional, AsyncGenerator
from dataclasses import dataclass
from datetime import datetime, timedelta
import json

from tion_btle import Tion, TionS3, TionLite, TionS4
from tion_btle.device_manager import DeviceManager, DeviceInfo
from tion_btle.scenarist import Scenario, Scenarist

_LOGGER = logging.getLogger(__name__)

@dataclass
class DeviceStatus:
    device_id: str
    state: str
    fan_speed: int
    heater_status: str
    last_updated: datetime
    error: Optional[str] = None

class Operator:
    """Central operator for managing Tion devices and scenarios."""
    
    def __init__(self, db_path: str = "devices.db"):
        self.device_manager = DeviceManager(db_path)
        self.scenarist = Scenarist(db_path)
        self._devices: Dict[str, Tion] = {}
        self._status_cache: Dict[str, DeviceStatus] = {}
        self._scenario_cache: Dict[int, Scenario] = {}
        self._polling_task: Optional[asyncio.Task] = None
        self._scenario_task: Optional[asyncio.Task] = None

    async def initialize(self) -> None:
        """Initialize operator with connected devices."""
        devices = self.device_manager.get_devices()
        for device in devices:
            await self._load_device(device)

    async def _load_device(self, device_info: DeviceInfo) -> Tion:
        """Load and connect to a Tion device."""
        device_class = {
            "TionS3": TionS3,
            "TionLite": TionLite,
            "TionS4": TionS4
        }.get(device_info.type, Tion)

        device = device_class(device_info.mac_address)
        await device.connect()
        self._devices[device_info.id] = device
        return device

    async def start_polling(self, interval: int = 60) -> None:
        """Start background polling of device statuses."""
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()

        self._polling_task = asyncio.create_task(self._poll_devices(interval))

    async def _poll_devices(self, interval: int) -> None:
        """Periodically poll all devices for status updates."""
        while True:
            try:
                for device_id, device in self._devices.items():
                    try:
                        status = await device.get()
                        self._status_cache[device_id] = DeviceStatus(
                            device_id=device_id,
                            state=status.get('state', 'unknown'),
                            fan_speed=status.get('fan_speed', 0),
                            heater_status=status.get('heater', 'off'),
                            last_updated=datetime.now()
                        )
                    except Exception as e:
                        _LOGGER.error(f"Failed to poll device {device_id}: {str(e)}")
                        self._status_cache[device_id] = DeviceStatus(
                            device_id=device_id,
                            state='error',
                            fan_speed=0,
                            heater_status='error',
                            last_updated=datetime.now(),
                            error=str(e)
                        )
            except Exception as e:
                _LOGGER.error(f"Polling error: {str(e)}")
            
            await asyncio.sleep(interval)

    async def get_device_status(self, device_id: str) -> DeviceStatus:
        """Get cached or fresh status for a device."""
        if device_id not in self._status_cache:
            device = self._devices.get(device_id)
            if not device:
                raise ValueError(f"Device {device_id} not loaded")
            status = await device.get()
            self._status_cache[device_id] = DeviceStatus(
                device_id=device_id,
                state=status['state'],
                fan_speed=status['fan_speed'],
                heater_status=status['heater'],
                last_updated=datetime.now()
            )
        return self._status_cache[device_id]

    async def execute_scenario(self, scenario_id: int) -> bool:
        """Execute a scenario by ID."""
        scenario = self.scenarist.get_scenario(scenario_id)
        if not scenario:
            return False

        device = self._devices.get(scenario.action_params.get('device_id'))
        if not device:
            return False

        try:
            await device.set(scenario.action_params)
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to execute scenario {scenario_id}: {str(e)}")
            return False

    async def run_scenarios(self) -> None:
        """Check and execute scenarios based on triggers."""
        if self._scenario_task and not self._scenario_task.done():
            self._scenario_task.cancel()

        self._scenario_task = asyncio.create_task(self._run_scenarios_loop())

    async def _run_scenarios_loop(self) -> None:
        """Continuous scenario checking loop."""
        while True:
            try:
                scenarios = self.scenarist.get_scenarios()
                for scenario in scenarios:
                    if await self._should_execute_scenario(scenario):
                        await self.execute_scenario(scenario.id)
            except Exception as e:
                _LOGGER.error(f"Scenario execution error: {str(e)}")
            await asyncio.sleep(60)

    async def _should_execute_scenario(self, scenario: Scenario) -> bool:
        """Determine if a scenario should be executed."""
        # Implement trigger checking logic here
        # Could check time-based or sensor-based triggers
        return False

    async def shutdown(self) -> None:
        """Cleanup resources."""
        if self._polling_task:
            self._polling_task.cancel()
        if self._scenario_task:
            self._scenario_task.cancel()
        
        for device in self._devices.values():
            await device.disconnect()
