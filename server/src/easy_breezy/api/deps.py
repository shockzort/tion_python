"""Зависимости API: контейнер подсистем и авторизация (план §12).

Зоны: ``/api/**`` — сессия-cookie или Bearer api-токен; health открыт.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, WebSocket

from easy_breezy.auth import SESSION_COOKIE
from easy_breezy.container import AppContainer
from easy_breezy.storage.models import User

_BEARER_PREFIX = "Bearer "


def get_container(request: Request) -> AppContainer:
    container: AppContainer = request.app.state.container
    return container


ContainerDep = Annotated[AppContainer, Depends(get_container)]


async def _resolve_user(
    container: AppContainer, *, session_token: str | None, bearer: str | None
) -> User | None:
    if session_token:
        user = await container.auth.session_user(session_token)
        if user is not None:
            return user
    if bearer:
        return await container.auth.api_token_user(bearer)
    return None


def _bearer_token(authorization: str | None) -> str | None:
    if authorization is not None and authorization.startswith(_BEARER_PREFIX):
        return authorization[len(_BEARER_PREFIX) :]
    return None


async def require_user(request: Request, container: ContainerDep) -> User:
    user = await _resolve_user(
        container,
        session_token=request.cookies.get(SESSION_COOKIE),
        bearer=_bearer_token(request.headers.get("Authorization")),
    )
    if user is None:
        raise HTTPException(status_code=401, detail="не авторизован")
    return user


UserDep = Annotated[User, Depends(require_user)]


async def websocket_user(websocket: WebSocket) -> User | None:
    """Авторизация WS: cookie браузера или ``?token=`` (api-токен)."""
    container: AppContainer = websocket.app.state.container
    return await _resolve_user(
        container,
        session_token=websocket.cookies.get(SESSION_COOKIE),
        bearer=_bearer_token(websocket.headers.get("Authorization"))
        or websocket.query_params.get("token"),
    )
