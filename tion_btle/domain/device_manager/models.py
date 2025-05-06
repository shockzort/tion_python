from dataclasses import dataclass
from typing import Optional, List, Dict

@dataclass
class DeviceInfo:
    """Domain model representing a Tion device"""
    id: str
    name: str
    type: str
    mac_address: str
    model: str
    is_active: bool = True
    is_paired: bool = False
    room: Optional[str] = None

@dataclass
class DeviceGroup:
    """Domain model representing a group of devices"""
    id: int
    name: str
    device_ids: List[str]
    is_active: bool = True
