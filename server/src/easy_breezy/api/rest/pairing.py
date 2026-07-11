"""Мастер сопряжения: скан эфира и пейринг (план §7, ADR-0003)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from easy_breezy.api.deps import ContainerDep, require_user
from easy_breezy.api.rest.devices import build_device_view
from easy_breezy.api.schemas import DeviceView
from easy_breezy.ble.transport import TransportError
from easy_breezy.core.pairing import PairingError
from easy_breezy.core.registry import DeviceExistsError

router = APIRouter(
    prefix="/api/pairing", tags=["pairing"], dependencies=[Depends(require_user)]
)

# фейковые MAC не-hex — паттерн мягче, чем у ручного добавления устройства
_SCANNED_MAC_PATTERN = r"^([0-9A-Za-z]{2}:){5}[0-9A-Za-z]{2}$"


class ScanBody(BaseModel):
    duration: float = Field(default=15.0, ge=3.0, le=30.0)


class FoundView(BaseModel):
    mac: str
    name: str
    rssi: int | None
    model_hint: str | None
    pairing_mode: bool | None
    registered: bool


class PairBody(BaseModel):
    mac: str = Field(pattern=_SCANNED_MAC_PATTERN)
    name: str = Field(min_length=1, max_length=100)


@router.post("/scan")
async def scan_air(body: ScanBody, container: ContainerDep) -> list[FoundView]:
    """Скан эфира; занятый чужим централом бризер не рекламируется (ADR-0005)."""
    try:
        found = await container.pairing.scan(body.duration)
    except TransportError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return [
        FoundView(
            mac=item.mac,
            name=item.name,
            rssi=item.rssi,
            model_hint=item.model_hint,
            pairing_mode=item.pairing_mode,
            registered=item.registered,
        )
        for item in found
    ]


@router.post("/pair", status_code=201)
async def pair_device(body: PairBody, container: ContainerDep) -> DeviceView:
    """Сопрягает бризер в режиме сопряжения; прогресс — WS pairing.progress."""
    try:
        device = await container.pairing.pair(body.mac.upper(), body.name)
    except DeviceExistsError as exc:
        raise HTTPException(
            status_code=409, detail="устройство уже зарегистрировано"
        ) from exc
    except PairingError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return build_device_view(device, container)
