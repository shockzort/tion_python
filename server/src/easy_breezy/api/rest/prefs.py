"""Пользовательские предпочтения: key/value JSON per-user.

UI хранит здесь настройки, которые должны переживать переустановку PWA
и быть одинаковыми на всех устройствах пользователя (панели графиков —
ключ ``charts``). Значение — произвольный JSON с ограничением размера.
"""

from __future__ import annotations

import json
import time
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from easy_breezy.api.deps import ContainerDep, UserDep
from easy_breezy.storage.repos import UserPrefRepo

router = APIRouter(prefix="/api", tags=["prefs"])

MAX_VALUE_CHARS = 16_384
"""Потолок сериализованного значения — защита от распухания БД."""

KeyParam = Annotated[str, Path(pattern=r"^[a-z0-9_-]{1,50}$")]


class PrefView(BaseModel):
    key: str
    value: Any


class PrefBody(BaseModel):
    value: Any


@router.get("/prefs/{key}")
async def get_pref(key: KeyParam, user: UserDep, container: ContainerDep) -> PrefView:
    """Значение предпочтения; отсутствующий ключ — value=null (не 404)."""
    async with container.db.session() as session:
        pref = await UserPrefRepo(session).get(user.id, key)
    return PrefView(key=key, value=None if pref is None else pref.value)


@router.put("/prefs/{key}")
async def put_pref(
    key: KeyParam, body: PrefBody, user: UserDep, container: ContainerDep
) -> PrefView:
    serialized = json.dumps(body.value, ensure_ascii=False)
    if len(serialized) > MAX_VALUE_CHARS:
        raise HTTPException(status_code=413, detail="значение слишком большое")
    async with container.db.session() as session:
        await UserPrefRepo(session).set(
            user.id, key, body.value, updated_at=int(time.time())
        )
    return PrefView(key=key, value=body.value)
