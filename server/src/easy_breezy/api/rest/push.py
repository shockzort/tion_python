"""Web push подписки (FR-32): ключ VAPID, подписка, отписка."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from easy_breezy.api.deps import ContainerDep, require_user

router = APIRouter(
    prefix="/api/push", tags=["push"], dependencies=[Depends(require_user)]
)


class VapidKey(BaseModel):
    key: str


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeBody(BaseModel):
    endpoint: str = Field(min_length=1, max_length=500)
    keys: SubscriptionKeys


class UnsubscribeBody(BaseModel):
    endpoint: str = Field(min_length=1, max_length=500)


@router.get("/vapid-key")
async def vapid_key(container: ContainerDep) -> VapidKey:
    return VapidKey(key=container.push.public_key)


@router.post("/subscriptions", status_code=201)
async def subscribe(body: SubscribeBody, container: ContainerDep) -> None:
    await container.push.subscribe(endpoint=body.endpoint, keys=body.keys.model_dump())


@router.post("/unsubscribe", status_code=204)
async def unsubscribe(body: UnsubscribeBody, container: ContainerDep) -> None:
    await container.push.unsubscribe(body.endpoint)
