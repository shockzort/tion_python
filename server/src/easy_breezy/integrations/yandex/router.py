"""Эндпоинты платформы Умного дома (план §6).

Авторизация — Bearer нашего OAuth-провайдера. /query отвечает только из
кэша состояния (live-BLE в запросном пути запрещён); /action превращает все
капабилити запроса в одну команду шины на устройство и ждёт итог 2.2 с:
успех/провал — честные DONE/ERROR, таймаут при живой команде — оптимистичный
DONE (истина доедет callback'ом), офлайн со свежестью хуже 120 с —
немедленный DEVICE_UNREACHABLE.
"""

from __future__ import annotations

import asyncio
import time
import uuid as uuid_module
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from easy_breezy.api.deps import ContainerDep, get_container
from easy_breezy.auth import hash_token
from easy_breezy.ble.supervisor import ConnectionState
from easy_breezy.container import AppContainer
from easy_breezy.core.bus import CommandError
from easy_breezy.core.model import state_to_dict
from easy_breezy.core.sensors import METRICS
from easy_breezy.core.sensors import STALE_AFTER_SECONDS as SENSOR_STALE
from easy_breezy.integrations.yandex import mapping
from easy_breezy.storage.models import CommandSource, CommandStatus, Device
from easy_breezy.storage.repos import DeviceRepo, RoomRepo, SensorRepo
from easy_breezy.storage.repos.oauth import OAuthRepo

log = structlog.get_logger(__name__)

ACTION_WAIT_SECONDS = 2.2
STALE_AFTER_SECONDS = 120.0

SENSOR_ID_PREFIX = "sensor:"

ERROR_UNREACHABLE = "DEVICE_UNREACHABLE"
ERROR_NOT_FOUND = "DEVICE_NOT_FOUND"

router = APIRouter(prefix="/v1.0", tags=["yandex"])


@router.head("")
@router.head("/")
async def ping() -> None:
    """Проверка доступности endpoint'а платформой (без авторизации)."""


async def require_linked_user(
    request: Request, container: Annotated[AppContainer, Depends(get_container)]
) -> int:
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="нет токена")
    token = authorization[len("Bearer ") :]
    async with container.db.session() as session:
        stored = await OAuthRepo(session).get_valid_by_access(
            hash_token(token), now=int(time.time())
        )
    if stored is None:
        raise HTTPException(status_code=401, detail="токен недействителен")
    return stored.user_id


LinkedUser = Annotated[int, Depends(require_linked_user)]
RequestId = Annotated[str | None, Header(alias="X-Request-Id")]


def _request_id(header: str | None) -> str:
    return header if header else uuid_module.uuid4().hex


class DeviceRef(BaseModel):
    id: str


class QueryBody(BaseModel):
    devices: list[DeviceRef]


class ActionCapability(BaseModel):
    type: str
    state: dict[str, Any]


class ActionDevice(BaseModel):
    id: str
    capabilities: list[ActionCapability]


class ActionPayload(BaseModel):
    devices: list[ActionDevice]


class ActionBody(BaseModel):
    payload: ActionPayload


@router.get("/user/devices")
async def list_devices(
    container: ContainerDep, user_id: LinkedUser, x_request_id: RequestId = None
) -> dict[str, Any]:
    async with container.db.session() as session:
        devices = await DeviceRepo(session).list_active()
        sensors = await SensorRepo(session).list_all()
        rooms = {room.id: room.name for room in await RoomRepo(session).list_all()}
    descriptors = [
        mapping.device_descriptor(
            device.uuid,
            device.name,
            rooms.get(device.room_id) if device.room_id else None,
        )
        for device in devices
    ]
    descriptors += [
        mapping.sensor_descriptor(
            f"{SENSOR_ID_PREFIX}{sensor.id}",
            sensor.name,
            rooms.get(sensor.room_id) if sensor.room_id else None,
            sorted(sensor.last_values) if sensor.last_values else list(METRICS),
        )
        for sensor in sensors
    ]
    return {
        "request_id": _request_id(x_request_id),
        "payload": {"user_id": str(user_id), "devices": descriptors},
    }


@router.post("/user/devices/query")
async def query_devices(
    body: QueryBody,
    container: ContainerDep,
    user_id: LinkedUser,
    x_request_id: RequestId = None,
) -> dict[str, Any]:
    """Состояния только из кэша — BLE в запросном пути запрещён (план §6)."""
    results: list[dict[str, Any]] = []
    for ref in body.devices:
        if ref.id.startswith(SENSOR_ID_PREFIX):
            results.append(await _sensor_query(container, ref.id))
            continue
        snapshot = container.cache.get(ref.id)
        if snapshot is None:
            results.append({"id": ref.id, "error_code": ERROR_NOT_FOUND})
        elif snapshot.state is None:
            results.append({"id": ref.id, "error_code": ERROR_UNREACHABLE})
        else:
            state = state_to_dict(snapshot.state)
            results.append(
                {
                    "id": ref.id,
                    "capabilities": mapping.capability_states(state),
                    "properties": mapping.property_states(state),
                }
            )
    return {
        "request_id": _request_id(x_request_id),
        "payload": {"devices": results},
    }


@router.post("/user/devices/action")
async def act_on_devices(
    body: ActionBody,
    container: ContainerDep,
    user_id: LinkedUser,
    x_request_id: RequestId = None,
) -> dict[str, Any]:
    request_id = _request_id(x_request_id)
    results = await asyncio.gather(
        *(
            _act_on_device(container, request_id, device)
            for device in body.payload.devices
        )
    )
    return {"request_id": request_id, "payload": {"devices": list(results)}}


@router.post("/user/unlink")
async def unlink(
    container: ContainerDep, user_id: LinkedUser, x_request_id: RequestId = None
) -> dict[str, Any]:
    async with container.db.session() as session:
        revoked = await OAuthRepo(session).revoke_for_user(user_id)
    log.info("yandex_unlinked", user_id=user_id, revoked=revoked)
    return {"request_id": _request_id(x_request_id)}


async def _sensor_query(container: AppContainer, ref_id: str) -> dict[str, Any]:
    """Датчик для /query: последние значения из реестра, стейл — недоступен."""
    try:
        sensor_id = int(ref_id.removeprefix(SENSOR_ID_PREFIX))
    except ValueError:
        return {"id": ref_id, "error_code": ERROR_NOT_FOUND}
    async with container.db.session() as session:
        sensor = await SensorRepo(session).get(sensor_id)
    if sensor is None:
        return {"id": ref_id, "error_code": ERROR_NOT_FOUND}
    stale = (
        sensor.last_seen_at is None or time.time() - sensor.last_seen_at > SENSOR_STALE
    )
    if stale or not sensor.last_values:
        return {"id": ref_id, "error_code": ERROR_UNREACHABLE}
    return {
        "id": ref_id,
        "properties": mapping.sensor_property_states(sensor.last_values),
    }


async def _act_on_device(
    container: AppContainer, request_id: str, device: ActionDevice
) -> dict[str, Any]:
    capabilities = [capability.model_dump() for capability in device.capabilities]

    if device.id.startswith(SENSOR_ID_PREFIX):
        return _device_result(
            device,
            error_code=mapping.ERROR_INVALID_ACTION,
            message="датчик не принимает команды",
        )

    stored = await _active_device(container, device.id)
    if stored is None:
        return _device_result(device, error_code=ERROR_NOT_FOUND)

    snapshot = container.cache.get(device.id)
    current = (
        state_to_dict(snapshot.state)
        if snapshot is not None and snapshot.state is not None
        else None
    )
    try:
        delta = mapping.actions_to_delta(capabilities, current)
    except mapping.ActionError as exc:
        return _device_result(device, error_code=exc.error_code, message=str(exc))

    # офлайн и давно не виделись — не мучаем очередь, отвечаем сразу (план §6)
    if container.registry.connection(device.id) is ConnectionState.DISCONNECTED:
        seen_at = snapshot.state_at if snapshot is not None else None
        if seen_at is None or time.time() - seen_at > STALE_AFTER_SECONDS:
            return _device_result(device, error_code=ERROR_UNREACHABLE)

    try:
        ticket = await container.bus.submit(
            device_uuid=device.id,
            delta=delta,
            source=CommandSource.YANDEX,
            idempotency_key=f"yandex:{request_id}:{device.id}",
        )
    except CommandError as exc:
        return _device_result(device, error_code=ERROR_UNREACHABLE, message=str(exc))

    try:
        outcome = await asyncio.wait_for(
            asyncio.shield(ticket.outcome), ACTION_WAIT_SECONDS
        )
    except TimeoutError:
        # команда жива — оптимистичный DONE, истину доставит callback state
        log.info("yandex_action_optimistic", device_uuid=device.id)
        return _device_result(device)
    if outcome.status is CommandStatus.DONE:
        return _device_result(device)
    return _device_result(device, error_code=ERROR_UNREACHABLE, message=outcome.error)


async def _active_device(container: AppContainer, device_id: str) -> Device | None:
    async with container.db.session() as session:
        device = await DeviceRepo(session).get(device_id)
    if device is None or device.deleted_at is not None:
        return None
    return device


def _device_result(
    device: ActionDevice, *, error_code: str | None = None, message: str | None = None
) -> dict[str, Any]:
    """Ответ per-device: результат применяется к каждой капабилити запроса."""
    action_result: dict[str, Any] = (
        {"status": "DONE"}
        if error_code is None
        else {"status": "ERROR", "error_code": error_code}
    )
    if message is not None and error_code is not None:
        action_result["error_message"] = message
    return {
        "id": device.id,
        "capabilities": [
            {
                "type": capability.type,
                "state": {
                    "instance": capability.state.get("instance", ""),
                    "action_result": action_result,
                },
            }
            for capability in device.capabilities
        ],
    }
