"""Yandex Smart Home API v1.0 routes."""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from api.middleware.auth import get_current_user, get_request_id
from api.schemas import (
    YandexActionRequest,
    YandexQueryPayload,
)

_LOGGER = logging.getLogger(__name__)

router = APIRouter(prefix="/v1.0")

YANDEX_DIALOGS_URL = "https://dialogs.yandex.net/api/v1/skills"
YANDEX_SKILL_ID = os.getenv("YANDEX_SKILL_ID", "")
YANDEX_CALLBACK_TOKEN = os.getenv("YANDEX_CALLBACK_TOKEN", "")

# Mode mapping for Yandex Alice modes → Tion modes
MODE_MAPPING: dict[str, Any] = {
    "auto": "auto",
    "manual": "outside",
    "recirculation": "recirculation",
    "mixed": "mixed",
    "тихий": {"fan_speed": 1},
    "турбо": {"fan_speed": 6},
    "ночной": {"fan_speed": 1, "sound": "off"},
    "проветривание": {"fan_speed": 4, "mode": "outside"},
}


def _get_operator(request: Request):  # type: ignore[no-untyped-def]
    """Get Operator from app state."""
    return request.app.state.operator


def _get_device_manager(request: Request):  # type: ignore[no-untyped-def]
    """Get DeviceManager from app state."""
    return request.app.state.device_manager


def _get_capabilities_for_device(device) -> list[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Build Yandex-format capabilities list for a device.

    Args:
        device: DeviceInfo object.

    Returns:
        List of capability dictionaries.
    """
    caps: list[dict[str, Any]] = [
        {
            "type": "devices.capabilities.on_off",
            "retrievable": True,
            "reportable": True,
        },
        {
            "type": "devices.capabilities.range",
            "retrievable": True,
            "reportable": True,
            "parameters": {
                "instance": "fan_speed",
                "unit": "unit.percent",
                "range": {"min": 1, "max": 6, "precision": 1},
            },
        },
    ]

    model = getattr(device, "model", "")
    if "S3" in model or "S4" in model:
        caps.append(
            {
                "type": "devices.capabilities.range",
                "retrievable": True,
                "reportable": True,
                "parameters": {
                    "instance": "temperature",
                    "unit": "unit.temperature.celsius",
                    "range": {"min": 10, "max": 30, "precision": 1},
                },
            }
        )

    if "S3" in model:
        caps.append(
            {
                "type": "devices.capabilities.mode",
                "retrievable": True,
                "reportable": True,
                "parameters": {
                    "instance": "work_mode",
                    "modes": [
                        {"value": "auto"},
                        {"value": "manual"},
                        {"value": "recirculation"},
                    ],
                },
            }
        )

    return caps


@router.head("/")
async def ping() -> Response:
    """Ping endpoint required by Yandex Smart Home protocol.

    Returns:
        Empty 200 response.
    """
    return Response(status_code=200)


@router.get("/user/devices")
async def get_user_devices(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> JSONResponse:
    """Return all registered devices with their capabilities.

    Args:
        request: FastAPI Request object.
        user_id: Yandex user ID from OAuth token.

    Returns:
        JSON response with devices list in Yandex Smart Home format.
    """
    request_id = get_request_id(request)
    device_manager = _get_device_manager(request)

    devices = []
    for device in device_manager.get_devices():
        devices.append(
            {
                "id": device.id,
                "name": device.name,
                "type": "devices.types.ventilation",
                "room": getattr(device, "room", None),
                "capabilities": _get_capabilities_for_device(device),
            }
        )

    return JSONResponse(
        content={
            "request_id": request_id,
            "payload": {
                "user_id": user_id,
                "devices": devices,
            },
        }
    )


@router.post("/user/devices/query")
async def query_devices(
    request: Request,
    body: YandexQueryPayload,
    user_id: str = Depends(get_current_user),
) -> JSONResponse:
    """Return current state of requested devices.

    Args:
        request: FastAPI Request object.
        body: Request payload with device IDs.
        user_id: Yandex user ID from OAuth token.

    Returns:
        JSON response with device states in Yandex Smart Home format.
    """
    request_id = get_request_id(request)
    operator = _get_operator(request)

    response_devices = []
    for dev in body.devices:
        device_id = dev.id
        try:
            status = await operator.get_device_status(device_id)
            caps: list[dict[str, Any]] = [
                {
                    "type": "devices.capabilities.on_off",
                    "state": {"instance": "on", "value": status.state == "on"},
                },
                {
                    "type": "devices.capabilities.range",
                    "state": {
                        "instance": "fan_speed",
                        "value": status.fan_speed * 100 / 6,
                    },
                },
            ]
            if status.heater_temp:
                caps.append(
                    {
                        "type": "devices.capabilities.range",
                        "state": {
                            "instance": "temperature",
                            "value": status.heater_temp,
                        },
                    }
                )
            if status.mode:
                mode_val = "manual"
                if status.mode == "recirculation":
                    mode_val = "recirculation"
                elif status.mode == "mixed":
                    mode_val = "mixed"
                caps.append(
                    {
                        "type": "devices.capabilities.mode",
                        "state": {"instance": "work_mode", "value": mode_val},
                    }
                )

            response_devices.append({"id": device_id, "capabilities": caps})

        except Exception as exc:
            _LOGGER.error(
                "Error querying device %s: %s", device_id, exc, exc_info=True
            )
            response_devices.append(
                {"id": device_id, "error_code": "DEVICE_UNREACHABLE"}
            )

    return JSONResponse(
        content={
            "request_id": request_id,
            "payload": {"devices": response_devices},
        }
    )


@router.post("/user/devices/action")
async def action_devices(
    request: Request,
    body: YandexActionRequest,
    user_id: str = Depends(get_current_user),
) -> JSONResponse:
    """Execute commands on devices.

    Args:
        request: FastAPI Request object.
        body: Request payload with device actions.
        user_id: Yandex user ID from OAuth token.

    Returns:
        JSON response with action results in Yandex Smart Home format.
    """
    request_id = get_request_id(request)
    operator = _get_operator(request)

    response_devices = []

    for dev in body.payload.devices:
        device_id = dev.id
        cap_results: list[dict[str, Any]] = []

        for cap in dev.capabilities:
            cap_type = cap.type
            result: dict[str, Any] = {"type": cap_type, "state": {"status": "ERROR"}}

            try:
                state_obj = cap.state
                if state_obj is None:
                    cap_results.append(result)
                    continue

                if cap_type == "devices.capabilities.on_off":
                    value = state_obj.value
                    device_state = "on" if value else "off"
                    success = await operator.set_device_state(device_id, device_state)
                    result["state"]["status"] = "DONE" if success else "ERROR"

                elif cap_type == "devices.capabilities.range":
                    instance = state_obj.instance
                    value = state_obj.value
                    if instance == "fan_speed":
                        speed = max(1, min(6, round(value * 6 / 100)))
                        success = await operator.set_fan_speed(device_id, speed)
                    elif instance == "temperature":
                        temp = max(10, min(30, int(value)))
                        success = await operator.set_heater_temp(device_id, temp)
                        await operator.set_heater_state(device_id, "on")
                    else:
                        success = False
                    result["state"]["status"] = "DONE" if success else "ERROR"

                elif cap_type == "devices.capabilities.mode":
                    instance = state_obj.instance
                    value = state_obj.value
                    if instance == "work_mode" and value in MODE_MAPPING:
                        mode_config = MODE_MAPPING[value]
                        success = True
                        if isinstance(mode_config, dict):
                            for param, param_value in mode_config.items():
                                if param == "fan_speed":
                                    success = success and await operator.set_fan_speed(
                                        device_id, param_value
                                    )
                                elif param == "mode":
                                    success = success and await operator.set_mode(
                                        device_id, param_value
                                    )
                                elif param == "sound":
                                    success = success and await operator.set_sound(
                                        device_id, param_value
                                    )
                        else:
                            success = await operator.set_mode(device_id, mode_config)
                    else:
                        success = False
                    result["state"]["status"] = "DONE" if success else "ERROR"

            except Exception as exc:
                _LOGGER.error(
                    "Error executing %s on %s: %s",
                    cap_type,
                    device_id,
                    exc,
                    exc_info=True,
                )
                result["state"]["status"] = "ERROR"
                result["state"]["error_code"] = "INTERNAL_ERROR"

            cap_results.append(result)

        response_devices.append({"id": device_id, "capabilities": cap_results})

    return JSONResponse(
        content={
            "request_id": request_id,
            "payload": {"devices": response_devices},
        }
    )


@router.post("/user/devices/unlink")
async def unlink_user(
    request: Request,
    user_id: str = Depends(get_current_user),
) -> JSONResponse:
    """Revoke user access (called when user unlinks the skill).

    Args:
        request: FastAPI Request object.
        user_id: Yandex user ID from OAuth token.

    Returns:
        Empty 200 response as required by Yandex protocol.
    """
    request_id = get_request_id(request)
    _LOGGER.info("User %s unlinked the Yandex skill", user_id)
    return JSONResponse(content={"request_id": request_id})


async def send_yandex_callback(
    user_id: str,
    devices_state: list[dict[str, Any]],
) -> bool:
    """Send state change push notification to Yandex.

    Args:
        user_id: Yandex user ID.
        devices_state: List of device state dicts.

    Returns:
        True if callback was sent successfully, False otherwise.
    """
    if not YANDEX_SKILL_ID or not YANDEX_CALLBACK_TOKEN:
        _LOGGER.warning(
            "YANDEX_SKILL_ID or YANDEX_CALLBACK_TOKEN not configured, "
            "skipping callback"
        )
        return False

    url = f"{YANDEX_DIALOGS_URL}/{YANDEX_SKILL_ID}/callback/state"
    payload = {
        "ts": time.time(),
        "payload": {
            "user_id": user_id,
            "devices": devices_state,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"OAuth {YANDEX_CALLBACK_TOKEN}",
                    "Content-Type": "application/json",
                },
            )
            if response.status_code == 202:
                _LOGGER.info("Yandex callback sent successfully for user %s", user_id)
                return True
            else:
                _LOGGER.warning(
                    "Yandex callback returned unexpected status %d: %s",
                    response.status_code,
                    response.text,
                )
                return False
    except httpx.HTTPError as exc:
        _LOGGER.error("Yandex callback HTTP error: %s", exc, exc_info=True)
        return False
    except Exception as exc:
        _LOGGER.error(
            "Unexpected error sending Yandex callback: %s", exc, exc_info=True
        )
        return False
