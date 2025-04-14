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
    """Complete state of a Tion device."""
    device_id: str
    state: str  # 'on' or 'off'
    fan_speed: int  # 0-6
    heater_status: str  # 'on' or 'off'
    heater_temp: int  # 10-30°C
    mode: str  # 'outside', 'recirculation', 'mixed'
    in_temp: int  # incoming air temp
    out_temp: int  # outgoing air temp 
    filter_remain: float  # days remaining
    sound: str  # 'on' or 'off'
    light: str  # 'on' or 'off' (for Lite models)
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
        self._retries = 3

    async def initialize(self) -> None:
        """Initialize operator with connected devices.

        Args:
            is_testing: If True, skips sleep delays for faster testing
        """
        devices = self.device_manager.get_devices()
        for device in devices:
            await self._load_device(device, self._retries)

    async def _load_device(
        self, device_info: DeviceInfo, retries: int = 3
    ) -> Optional[Tion]:
        """Load and connect to a Tion device with retry logic.

        Args:
            device_info: Device information
            retries: Number of connection attempts
            is_testing: If True, skips sleep delays for faster testing
        """
        device_class = {"TionS3": TionS3, "TionLite": TionLite, "TionS4": TionS4}.get(
            device_info.type, Tion
        )

        device = device_class(device_info.mac_address)

        for attempt in range(1, retries + 1):
            try:
                await device.connect()
                self._devices[device_info.id] = device
                _LOGGER.info(f"Successfully connected to device {device_info.id}")
                return device
            except Exception as e:
                _LOGGER.warning(
                    f"Connection attempt {attempt}/{retries} failed for {device_info.id}: {str(e)}"
                )
                if attempt < retries:
                    await asyncio.sleep(2**attempt)  # Exponential backoff

        _LOGGER.error(
            f"Failed to connect to device {device_info.id} after {retries} attempts"
        )
        return None

    async def start_polling(self, interval: int = 60) -> None:
        """Start device status polling.

        Args:
            interval: Time between polls in seconds
        """
        if self._polling_task and not self._polling_task.done():
            self._polling_task.cancel()

        self._polling_task = asyncio.create_task(self._poll_devices(interval))

    async def _update_devices_status(self):
        """Update device status.

        Args:
            none
        """

        try:
            active_devices = self.device_manager.get_connected_devices()

            for device_id, device_info in active_devices.items():
                try:
                    # Get or create device instance
                    device = self._devices.get(device_id)
                    if not device:
                        device = await self._load_device(device_info)
                        if not device:
                            continue

                    # Check connection status
                    if not device.connection_status:
                        _LOGGER.warning(
                            f"Device {device_id} disconnected, attempting to reconnect"
                        )
                        await device.connect()

                    # Get fresh status
                    status = await device.get()
                    self._status_cache[device_id] = DeviceStatus(
                        device_id=device_id,
                        state=status.get("state", "unknown"),
                        fan_speed=status.get("fan_speed", 0),
                        heater_status=status.get("heater", "off"),
                        heater_temp=status.get("heater_temp", 0),
                        mode=status.get("mode", "outside"),
                        in_temp=status.get("in_temp", 0),
                        out_temp=status.get("out_temp", 0),
                        filter_remain=status.get("filter_remain", 0),
                        sound=status.get("sound", "off"),
                        light=status.get("light", "off"),
                        last_updated=datetime.now(),
                    )

                except Exception as e:
                    _LOGGER.error(f"Failed to poll device {device_id}: {str(e)}")
                    self._status_cache[device_id] = DeviceStatus(
                        device_id=device_id,
                        state="error",
                        fan_speed=0,
                        heater_status="error",
                        heater_temp=0,
                        mode="unknown",
                        in_temp=0,
                        out_temp=0,
                        filter_remain=0,
                        sound="off",
                        light="off",
                        last_updated=datetime.now(),
                        error=str(e),
                    )

                    # Try to reconnect on next iteration
                    if device_id in self._devices:
                        del self._devices[device_id]

        except Exception as e:
            _LOGGER.error(f"Polling error: {str(e)}")

    async def _poll_devices(self, interval: int) -> None:
        """Poll all devices with reconnection logic.

        Args:
            interval: Time between polls in seconds
        """
        while True:
            await self._update_devices_status()
            await asyncio.sleep(interval)

    async def get_device_status(self, device_id: str, force_refresh: bool = False) -> DeviceStatus:
        """Get complete device status, optionally forcing a fresh read.
        
        Args:
            device_id: Device identifier
            force_refresh: If True, bypass cache and read fresh state
            
        Returns:
            DeviceStatus with all state information
            
        Raises:
            ValueError: If device not found
            TionException: If communication error occurs
        """
        if force_refresh or device_id not in self._status_cache:
            device = self._devices.get(device_id)
            if not device:
                raise ValueError(f"Device {device_id} not loaded")
                
            status = await device.get()
            self._status_cache[device_id] = DeviceStatus(
                device_id=device_id,
                state=status["state"],
                fan_speed=status["fan_speed"],
                heater_status=status["heater"],
                heater_temp=status["heater_temp"],
                mode=status.get("mode", "outside"),
                in_temp=status["in_temp"],
                out_temp=status["out_temp"],
                filter_remain=status["filter_remain"],
                sound=status.get("sound", "off"),
                light=status.get("light", "off"),
                last_updated=datetime.now(),
            )
        return self._status_cache[device_id]

    async def set_device_state(self, device_id: str, state: str) -> bool:
        """Turn device on/off.
        
        Args:
            device_id: Device identifier
            state: 'on' or 'off'
            
        Returns:
            True if successful, False otherwise
            
        Raises:
            ValueError: If state is not 'on' or 'off'
        """
        if state not in ("on", "off"):
            raise ValueError("State must be either 'on' or 'off'")
        return await self._set_device_property(device_id, "state", state)

    async def set_fan_speed(self, device_id: str, speed: int) -> bool:
        """Set fan speed (0-6).
        
        Args:
            device_id: Device identifier 
            speed: 0 (off) to 6 (max)
            
        Returns:
            True if successful, False otherwise
        """
        if speed < 0 or speed > 6:
            raise ValueError("Fan speed must be between 0 and 6")
        return await self._set_device_property(device_id, "fan_speed", speed)

    async def set_heater_state(self, device_id: str, state: str) -> bool:
        """Enable/disable heater.
        
        Args:
            device_id: Device identifier
            state: 'on' or 'off'
            
        Returns:
            True if successful, False otherwise
        """
        return await self._set_device_property(device_id, "heater", state)

    async def set_heater_temp(self, device_id: str, temp: int) -> bool:
        """Set heater target temperature (10-30°C).
        
        Args:
            device_id: Device identifier
            temp: Target temperature in °C
            
        Returns:
            True if successful, False otherwise
        """
        if temp < 10 or temp > 30:
            raise ValueError("Temperature must be between 10 and 30°C")
        return await self._set_device_property(device_id, "heater_temp", temp)

    async def set_mode(self, device_id: str, mode: str) -> bool:
        """Set ventilation mode.
        
        Args:
            device_id: Device identifier
            mode: 'outside', 'recirculation' or 'mixed'
            
        Returns:
            True if successful, False otherwise
        """
        return await self._set_device_property(device_id, "mode", mode)

    async def set_sound(self, device_id: str, state: str) -> bool:
        """Enable/disable sound notifications.
        
        Args:
            device_id: Device identifier
            state: 'on' or 'off'
            
        Returns:
            True if successful, False otherwise
        """
        return await self._set_device_property(device_id, "sound", state)

    async def set_light(self, device_id: str, state: str) -> bool:
        """Enable/disable LED light (Lite models only).
        
        Args:
            device_id: Device identifier
            state: 'on' or 'off'
            
        Returns:
            True if successful, False otherwise
        """
        return await self._set_device_property(device_id, "light", state)

    async def _set_device_property(self, device_id: str, prop: str, value) -> bool:
        """Internal helper to set device properties."""
        device = self._devices.get(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not loaded")
            
        try:
            await device.set({prop: value})
            # Invalidate cache
            if device_id in self._status_cache:
                del self._status_cache[device_id]
            return True
        except Exception as e:
            _LOGGER.error(f"Failed to set {prop}={value} on {device_id}: {str(e)}")
            return False

    async def execute_scenario(self, scenario_id: int) -> bool:
        """Execute a scenario by ID with full tracking."""
        scenario = self.scenarist.get_scenario(scenario_id)
        if not scenario:
            _LOGGER.warning(f"Scenario {scenario_id} not found")
            return False

        if not self.scenarist.validate_action_params(scenario.action_params):
            _LOGGER.error(f"Invalid action params for scenario {scenario_id}")
            return False

        device_id = scenario.action_params.get("device_id")
        device = self._devices.get(device_id)
        if not device:
            _LOGGER.warning(
                f"Device {device_id} not connected for scenario {scenario_id}"
            )
            return False

        try:
            # Check device capabilities before executing
            capabilities = self.device_manager.get_device_capabilities(device_id)
            command = scenario.action_params["command"]

            if command == "set_temp" and not capabilities["temperature_control"]:
                _LOGGER.error(f"Device {device_id} doesn't support temperature control")
                return False

            if command == "set_mode" and not capabilities["mode_control"]:
                _LOGGER.error(f"Device {device_id} doesn't support mode control")
                return False

            # Execute the command
            success = await device.set(scenario.action_params)

            # Update scenario execution tracking
            scenario.last_executed = datetime.now()
            scenario.execution_count += 1
            scenario.last_status = success

            _LOGGER.info(
                f"Executed scenario {scenario_id} on device {device_id} - {'Success' if success else 'Failed'}"
            )
            return success

        except Exception as e:
            _LOGGER.error(f"Failed to execute scenario {scenario_id}: {str(e)}")
            scenario.last_executed = datetime.now()
            scenario.execution_count += 1
            scenario.last_status = False
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
        """Check if scenario should be executed based on triggers."""
        if not scenario.is_active:
            return False

        # Time-based triggers
        if scenario.trigger_type == "time":
            now = datetime.now().time()
            start = datetime.strptime(scenario.trigger_params["start"], "%H:%M").time()
            end = datetime.strptime(scenario.trigger_params["end"], "%H:%M").time()

            if start <= end:
                return start <= now <= end
            else:  # Overnight range
                return now >= start or now <= end

        # Sensor-based triggers
        elif scenario.trigger_type == "sensor":
            device_id = scenario.trigger_params.get("device_id")
            if not device_id:
                return False

            status = await self.get_device_status(device_id)
            if not status:
                return False

            sensor_type = scenario.trigger_params["sensor"]
            threshold = scenario.trigger_params["threshold"]
            comparison = scenario.trigger_params.get("comparison", "gt")

            current_value = getattr(status, sensor_type, None)
            if current_value is None:
                return False

            if comparison == "gt":
                return current_value > threshold
            elif comparison == "lt":
                return current_value < threshold
            elif comparison == "eq":
                return current_value == threshold

        return False

    async def reconnect_device(self, device_id: str) -> bool:
        """Reconnect to a specific device."""
        device_info = self.device_manager.get_device(device_id)
        if not device_info:
            _LOGGER.error(f"Device {device_id} not found in registry")
            return False

        if device_id in self._devices:
            try:
                await self._devices[device_id].disconnect()
            except Exception:
                pass
            del self._devices[device_id]

        device = await self._load_device(device_info)
        return device is not None

    async def shutdown(self) -> None:
        """Cleanup resources."""
        if self._polling_task:
            self._polling_task.cancel()
            try:
                await self._polling_task
            except asyncio.CancelledError:
                pass

        if self._scenario_task:
            self._scenario_task.cancel()
            try:
                await self._scenario_task
            except asyncio.CancelledError:
                pass

        for device_id, device in list(self._devices.items()):
            try:
                await device.disconnect()
            except Exception as e:
                _LOGGER.error(f"Error disconnecting device {device_id}: {str(e)}")
            finally:
                del self._devices[device_id]
