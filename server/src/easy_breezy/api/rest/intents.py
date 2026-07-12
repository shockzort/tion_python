"""Текстовые интенты: POST /api/intents/execute (FR-30/31)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from easy_breezy.api.deps import ContainerDep, require_user

router = APIRouter(
    prefix="/api", tags=["intents"], dependencies=[Depends(require_user)]
)


class IntentBody(BaseModel):
    text: str = Field(min_length=1, max_length=300)


class IntentView(BaseModel):
    reply: str
    executed: bool
    intent: str | None


@router.post("/intents/execute")
async def execute_intent(body: IntentBody, container: ContainerDep) -> IntentView:
    result = await container.intents.execute(body.text)
    return IntentView(
        reply=result.reply, executed=result.executed, intent=result.intent
    )
