from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from tion_btle.domain.device_manager.models import DeviceInfo, DeviceGroup

class IDeviceStorage(ABC):
    """Interface for device persistence operations"""
    
    @abstractmethod
    def get_devices(self, active_only: bool = True) -> List[DeviceInfo]: 
        """Get all devices"""
        pass
    
    @abstractmethod 
    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Get single device by ID"""
        pass
    
    @abstractmethod
    def create_device(self, device: DeviceInfo) -> bool:
        """Create new device"""
        pass
    
    @abstractmethod
    def update_device(self, device_id: str, **kwargs) -> bool:
        """Update device properties"""
        pass
    
    @abstractmethod 
    def delete_device(self, device_id: str) -> bool:
        """Mark device as inactive"""
        pass

class IDeviceGroupStorage(ABC):
    """Interface for device group operations"""
    
    @abstractmethod
    def get_groups(self, active_only: bool = True) -> List[DeviceGroup]:
        """Get all device groups"""
        pass
    
    @abstractmethod
    def create_group(self, name: str, device_ids: List[str]) -> int:
        """Create new device group"""
        pass
    
    @abstractmethod
    def update_group(self, group_id: int, **kwargs) -> bool:
        """Update group properties"""
        pass
    
    @abstractmethod
    def delete_group(self, group_id: int) -> bool:
        """Mark group as inactive"""
        pass
