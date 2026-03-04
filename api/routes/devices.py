"""REST API endpoints for device management."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from api.middleware.auth import get_current_user
from api.schemas import (
    BLEDeviceSchema,
    DeviceCommandRequest,
    DeviceCommandResponse,
    DeviceResponse,
    DevicesListResponse,
    DeviceStatusResponse,
    DiscoverResponse,
    RegisterRequest,
)

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/api/devices")


def _get_operator(request: Request):  # type: ignore[no-untyped-def]
    """Get Operator from app state."""
    return request.app.state.operator


def _get_device_manager(request: Request):  # type: ignore[no-untyped-def]
    """Get DeviceManager from app state."""
    return request.app.state.device_manager


@router.post("/discover", response_model=DiscoverResponse)
async def discover_devices(
    request: Request,
    _user_id: str = Depends(get_current_user),
) -> DiscoverResponse:
    """Start BLE scanning and return found devices.

    Args:
        request: FastAPI Request object.
        _user_id: Authenticated user ID (unused, just for auth).

    Returns:
        List of discovered BLE devices.
    """
    device_manager = _get_device_manager(request)
    try:
        ble_devices = await device_manager.discover_devices()
        return DiscoverResponse(
            devices=[
                BLEDeviceSchema(
                    name=d.name or "",
                    address=d.address,
                    rssi=getattr(d, "rssi", None),
                )
                for d in ble_devices
            ]
        )
    except Exception as exc:
        _LOGGER.error("BLE discovery failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Discovery failed: {exc}") from exc


@router.post("/register", response_model=DeviceResponse)
async def register_device(
    request: Request,
    body: RegisterRequest,
    _user_id: str = Depends(get_current_user),
) -> DeviceResponse:
    """Register a discovered device into the system.

    Args:
        request: FastAPI Request object.
        body: Registration request with device details.
        _user_id: Authenticated user ID.

    Returns:
        Registered device information.
    """
    device_manager = _get_device_manager(request)
    operator = _get_operator(request)

    try:
        device = await device_manager.register_device(
            name=body.name,
            mac_address=body.mac_address,
            model=body.model,
            room=body.room,
        )

        if body.auto_pair:
            try:
                await operator.device_manager.pair_device(device.id)
            except Exception as exc:
                _LOGGER.warning(
                    "Auto-pair failed for device %s: %s", device.id, exc
                )

        return DeviceResponse(
            id=device.id,
            name=device.name,
            type=device.type,
            mac_address=device.mac_address,
            model=device.model,
            room=getattr(device, "room", None),
            is_active=device.is_active,
            is_paired=device.is_paired,
        )
    except Exception as exc:
        _LOGGER.error("Device registration failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Registration failed: {exc}"
        ) from exc


@router.get("", response_model=DevicesListResponse)
async def list_devices(
    request: Request,
    _user_id: str = Depends(get_current_user),
) -> DevicesListResponse:
    """Return list of all registered devices.

    Args:
        request: FastAPI Request object.
        _user_id: Authenticated user ID.

    Returns:
        List of registered devices.
    """
    device_manager = _get_device_manager(request)
    devices = device_manager.get_devices()
    return DevicesListResponse(
        devices=[
            DeviceResponse(
                id=d.id,
                name=d.name,
                type=d.type,
                mac_address=d.mac_address,
                model=d.model,
                room=getattr(d, "room", None),
                is_active=d.is_active,
                is_paired=d.is_paired,
            )
            for d in devices
        ]
    )


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(
    device_id: str,
    request: Request,
    _user_id: str = Depends(get_current_user),
) -> DeviceResponse:
    """Return details of a specific device.

    Args:
        device_id: Device identifier.
        request: FastAPI Request object.
        _user_id: Authenticated user ID.

    Returns:
        Device details.

    Raises:
        HTTPException: 404 if device not found.
    """
    device_manager = _get_device_manager(request)
    device = device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    return DeviceResponse(
        id=device.id,
        name=device.name,
        type=device.type,
        mac_address=device.mac_address,
        model=device.model,
        room=getattr(device, "room", None),
        is_active=device.is_active,
        is_paired=device.is_paired,
    )


@router.delete("/{device_id}")
async def delete_device(
    device_id: str,
    request: Request,
    _user_id: str = Depends(get_current_user),
) -> dict[str, str]:
    """Soft-delete a device (set is_active=False).

    Args:
        device_id: Device identifier.
        request: FastAPI Request object.
        _user_id: Authenticated user ID.

    Returns:
        Confirmation message.

    Raises:
        HTTPException: 404 if device not found.
    """
    device_manager = _get_device_manager(request)
    device = device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    try:
        await device_manager.delete_device(device_id)
        return {"message": f"Device {device_id} deactivated"}
    except Exception as exc:
        _LOGGER.error("Failed to delete device %s: %s", device_id, exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to delete device: {exc}"
        ) from exc


@router.get("/{device_id}/status", response_model=DeviceStatusResponse)
async def get_device_status(
    device_id: str,
    request: Request,
    _user_id: str = Depends(get_current_user),
) -> DeviceStatusResponse:
    """Get current status of a device via BLE.

    Args:
        device_id: Device identifier.
        request: FastAPI Request object.
        _user_id: Authenticated user ID.

    Returns:
        Current device status.

    Raises:
        HTTPException: 404 if device not found, 503 if device unreachable.
    """
    operator = _get_operator(request)
    try:
        status = await operator.get_device_status(device_id, force_refresh=True)
        return DeviceStatusResponse(
            device_id=status.device_id,
            state=status.state,
            fan_speed=status.fan_speed,
            heater_status=status.heater_status,
            heater_temp=status.heater_temp,
            mode=status.mode,
            in_temp=status.in_temp,
            out_temp=status.out_temp,
            filter_remain=status.filter_remain,
            sound=status.sound,
            light=status.light,
            error=status.error,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _LOGGER.error(
            "Failed to get status for device %s: %s", device_id, exc, exc_info=True
        )
        raise HTTPException(
            status_code=503, detail=f"Device unreachable: {exc}"
        ) from exc


@router.post("/{device_id}/command", response_model=DeviceCommandResponse)
async def send_command(
    device_id: str,
    request: Request,
    body: DeviceCommandRequest,
    _user_id: str = Depends(get_current_user),
) -> DeviceCommandResponse:
    """Send a command to a device.

    Args:
        device_id: Device identifier.
        request: FastAPI Request object.
        body: Command request with command name and value.
        _user_id: Authenticated user ID.

    Returns:
        Command execution result.
    """
    operator = _get_operator(request)
    command = body.command
    value = body.value

    try:
        success = False
        if command == "set_state":
            success = await operator.set_device_state(device_id, str(value))
        elif command == "set_fan_speed":
            success = await operator.set_fan_speed(device_id, int(value))
        elif command == "set_heater_state":
            success = await operator.set_heater_state(device_id, str(value))
        elif command == "set_heater_temp":
            success = await operator.set_heater_temp(device_id, int(value))
        elif command == "set_mode":
            success = await operator.set_mode(device_id, str(value))
        elif command == "set_sound":
            success = await operator.set_sound(device_id, str(value))
        elif command == "set_light":
            success = await operator.set_light(device_id, str(value))
        else:
            raise HTTPException(
                status_code=400, detail=f"Unknown command: {command}"
            )

        return DeviceCommandResponse(
            success=success,
            device_id=device_id,
            command=command,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        _LOGGER.error(
            "Command %s failed for device %s: %s", command, device_id, exc, exc_info=True
        )
        return DeviceCommandResponse(
            success=False,
            device_id=device_id,
            command=command,
            error=str(exc),
        )


@router.post("/{device_id}/pair")
async def pair_device(
    device_id: str,
    request: Request,
    _user_id: str = Depends(get_current_user),
) -> dict[str, str | bool]:
    """Initiate BLE pairing with a device.

    Args:
        device_id: Device identifier.
        request: FastAPI Request object.
        _user_id: Authenticated user ID.

    Returns:
        Pairing result.
    """
    device_manager = _get_device_manager(request)
    try:
        await device_manager.pair_device(device_id)
        return {"device_id": device_id, "paired": True}
    except Exception as exc:
        _LOGGER.error("Pairing failed for device %s: %s", device_id, exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Pairing failed: {exc}"
        ) from exc
