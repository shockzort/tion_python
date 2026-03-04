"""Pydantic schemas for API requests and responses."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Generic / shared
# ---------------------------------------------------------------------------


class ErrorResponse(BaseModel):
    """Generic error response."""

    error: str
    detail: str | None = None


# ---------------------------------------------------------------------------
# Yandex Smart Home schemas
# ---------------------------------------------------------------------------


class YandexCapabilityState(BaseModel):
    """Capability state value."""

    instance: str
    value: Any


class YandexCapability(BaseModel):
    """Yandex Smart Home capability."""

    type: str
    state: YandexCapabilityState | None = None


class YandexDevice(BaseModel):
    """Device reference in Yandex requests."""

    id: str
    capabilities: list[YandexCapability] = Field(default_factory=list)


class YandexQueryPayload(BaseModel):
    """Payload for /user/devices/query."""

    devices: list[YandexDevice]


class YandexActionPayload(BaseModel):
    """Payload for /user/devices/action."""

    devices: list[YandexDevice]


class YandexActionRequest(BaseModel):
    """Request body for /user/devices/action."""

    payload: YandexActionPayload


class YandexCapabilityResult(BaseModel):
    """Result of a single capability action."""

    type: str
    state: dict[str, Any]


class YandexDeviceActionResult(BaseModel):
    """Result of actions on a single device."""

    id: str
    capabilities: list[YandexCapabilityResult] = Field(default_factory=list)


class YandexDeviceStateResult(BaseModel):
    """State result for a single device."""

    id: str
    capabilities: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None


class YandexCapabilityInfo(BaseModel):
    """Capability info in device list response."""

    type: str
    retrievable: bool = True
    reportable: bool = True
    parameters: dict[str, Any] | None = None


class YandexDeviceInfo(BaseModel):
    """Full device info in /user/devices response."""

    id: str
    name: str
    type: str
    room: str | None = None
    capabilities: list[YandexCapabilityInfo] = Field(default_factory=list)


class YandexUserDevicesPayload(BaseModel):
    """Payload of /user/devices response."""

    user_id: str
    devices: list[YandexDeviceInfo]


class YandexUserDevicesResponse(BaseModel):
    """Response for GET /v1.0/user/devices."""

    request_id: str
    payload: YandexUserDevicesPayload


class YandexQueryResponse(BaseModel):
    """Response for POST /v1.0/user/devices/query."""

    request_id: str
    payload: dict[str, list[YandexDeviceStateResult]]


class YandexActionResponse(BaseModel):
    """Response for POST /v1.0/user/devices/action."""

    request_id: str
    payload: dict[str, list[YandexDeviceActionResult]]


# ---------------------------------------------------------------------------
# Device management schemas
# ---------------------------------------------------------------------------


class BLEDeviceSchema(BaseModel):
    """BLE device discovered during scanning."""

    name: str
    address: str
    rssi: int | None = None


class DiscoverResponse(BaseModel):
    """Response for POST /api/devices/discover."""

    devices: list[BLEDeviceSchema]


class RegisterRequest(BaseModel):
    """Request body for POST /api/devices/register."""

    name: str
    mac_address: str
    model: str
    room: str | None = None
    auto_pair: bool = False


class DeviceResponse(BaseModel):
    """Single registered device response."""

    id: str
    name: str
    type: str
    mac_address: str
    model: str
    room: str | None = None
    is_active: bool
    is_paired: bool


class DevicesListResponse(BaseModel):
    """Response for GET /api/devices."""

    devices: list[DeviceResponse]


class DeviceStatusResponse(BaseModel):
    """Response for GET /api/devices/{device_id}/status."""

    device_id: str
    state: str
    fan_speed: int
    heater_status: str
    heater_temp: int
    mode: str
    in_temp: int
    out_temp: int
    filter_remain: float
    sound: str
    light: str
    error: str | None = None


class DeviceCommandRequest(BaseModel):
    """Request body for POST /api/devices/{device_id}/command."""

    command: str
    value: Any = None


class DeviceCommandResponse(BaseModel):
    """Response for POST /api/devices/{device_id}/command."""

    success: bool
    device_id: str
    command: str
    error: str | None = None
