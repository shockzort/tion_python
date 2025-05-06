import asyncio
import logging
from typing import List, Dict, Optional
from bleak import BleakScanner
from bleak.backends.device import BLEDevice

from .interfaces import IDeviceStorage, IDeviceGroupStorage
from .models import DeviceInfo
from tion_btle import Tion, TionS3, TionLite, TionS4

_LOGGER = logging.getLogger(__name__)

class DeviceManager:
    """Core domain service for managing Tion devices"""
    
    TION_DEVICE_PREFIXES = ("Tion_Breezer_", "tion_")

    def __init__(
        self,
        device_storage: IDeviceStorage,
        group_storage: IDeviceGroupStorage
    ):
        self.device_storage = device_storage
        self.group_storage = group_storage

    async def discover_devices(self) -> List[BLEDevice]:
        """Discover Tion BLE devices in range"""
        devices = await BleakScanner.discover()
        return [
            d for d in devices
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
        self, 
        device: BLEDevice, 
        name: str = None, 
        auto_pair: bool = False
    ) -> DeviceInfo:
        """Register new device"""
        device_class = self.get_device_class(device.name)
        device_info = DeviceInfo(
            id=device.address,
            name=name or self._generate_device_name(device.name),
            type=device_class.__name__,
            mac_address=device.address,
            model=device_class.__name__.replace("Tion", ""),
        )

        self.device_storage.create_device(device_info)

        if auto_pair:
            await self.pair_device(device_info.id)

        return device_info

    def _generate_device_name(self, device_name: str) -> str:
        """Generate human-friendly device name"""
        return device_name.replace("Tion_Breezer_", "").replace("_", " ").title()

    def get_devices(self, active_only: bool = True) -> List[DeviceInfo]:
        """Get list of registered devices"""
        return self.device_storage.get_devices(active_only)

    def get_connected_devices(self) -> Dict[str, DeviceInfo]:
        """Get dictionary of currently connected devices"""
        devices = self.device_storage.get_devices()
        return {d.id: d for d in devices if d.is_active and d.is_paired}

    def get_device_capabilities(self, device_id: str) -> Dict[str, bool]:
        """Get device capabilities based on its type"""
        device = self.device_storage.get_device(device_id)
        if not device:
            return {}

        return {
            "fan_control": True,
            "heater_control": "S3" in device.type or "S4" in device.type,
            "temperature_control": "S3" in device.type or "S4" in device.type,
            "light_control": "Lite" in device.type,
            "mode_control": "S4" in device.type,
        }

    def get_device_groups(self, active_only: bool = True) -> List[Dict]:
        """Get list of device groups"""
        return self.group_storage.get_groups(active_only)

    def create_device_group(self, name: str, device_ids: List[str]) -> int:
        """Create new device group"""
        return self.group_storage.create_group(name, device_ids)

    def update_device_group(self, group_id: int, **kwargs) -> bool:
        """Update device group properties"""
        return self.group_storage.update_group(group_id, **kwargs)

    def delete_device_group(self, group_id: int) -> bool:
        """Mark device group as inactive"""
        return self.group_storage.delete_group(group_id)

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Get single device by ID"""
        return self.device_storage.get_device(device_id)

    def update_device(self, device_id: str, **kwargs) -> bool:
        """Update device properties"""
        return self.device_storage.update_device(device_id, **kwargs)

    async def delete_device(self, device_id: str) -> bool:
        """Mark device as inactive and unpair it"""
        await self.unpair_device(device_id)
        return self.device_storage.delete_device(device_id)

    async def pair_device(self, device_id: str, timeout: int = 30) -> bool:
        """Pair with device using Tion's pair() method"""
        device_info = self.device_storage.get_device(device_id)
        if not device_info:
            raise ValueError(f"Device {device_id} not found")

        device_class = self.get_device_class(device_info.name)
        device = device_class(device_info.mac_address)

        try:
            _LOGGER.info(f"Starting pairing process for {device_id}, timeout: {timeout}s")
            await asyncio.wait_for(device.pair(), timeout=timeout)

            self.device_storage.update_device(
                device_id,
                is_paired=True
            )
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
        device_info = self.device_storage.get_device(device_id)
        if not device_info or not device_info.is_paired:
            return False

        device_class = self.get_device_class(device_info.type)
        device = device_class(device_info.mac_address)

        try:
            await device._btle.unpair()
            self.device_storage.update_device(
                device_id,
                is_paired=False
            )
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
