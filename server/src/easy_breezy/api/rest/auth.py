"""Эндпоинты авторизации: setup, логин/логаут, api-токены."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from easy_breezy.api.deps import ContainerDep, UserDep
from easy_breezy.auth import SESSION_COOKIE, AuthError, SetupError, ThrottledError

router = APIRouter(prefix="/api", tags=["auth"])


class SetupBody(BaseModel):
    setup_token: str
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)


class LoginBody(BaseModel):
    username: str
    password: str


class UserView(BaseModel):
    id: int
    username: str


class TokenCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class TokenCreated(BaseModel):
    id: int
    name: str
    token: str
    """Сырое значение — показывается один раз."""


class TokenView(BaseModel):
    id: int
    name: str
    created_at: int
    last_used_at: int | None


def _set_session_cookie(
    response: Response, container: ContainerDep, token: str
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=container.settings.session_ttl_days * 86400,
        httponly=True,
        samesite="lax",
        secure=container.settings.session_cookie_secure,
    )


@router.post("/auth/setup", status_code=201)
async def setup_admin(
    body: SetupBody, response: Response, container: ContainerDep
) -> UserView:
    """Создаёт первого администратора по setup-токену из лога и логинит его."""
    try:
        user = await container.auth.create_admin(
            setup_token=body.setup_token,
            username=body.username,
            password=body.password,
        )
    except SetupError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    token, _ = await container.auth.login(body.username, body.password)
    _set_session_cookie(response, container, token)
    return UserView(id=user.id, username=user.username)


@router.post("/auth/login")
async def login(
    body: LoginBody, response: Response, container: ContainerDep
) -> UserView:
    try:
        token, user = await container.auth.login(body.username, body.password)
    except ThrottledError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_session_cookie(response, container, token)
    return UserView(id=user.id, username=user.username)


@router.post("/auth/logout", status_code=204)
async def logout(
    request: Request, response: Response, container: ContainerDep, _user: UserDep
) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await container.auth.logout(token)
    response.delete_cookie(SESSION_COOKIE)


@router.get("/auth/me")
async def me(user: UserDep) -> UserView:
    return UserView(id=user.id, username=user.username)


@router.post("/tokens", status_code=201)
async def create_token(
    body: TokenCreate, container: ContainerDep, user: UserDep
) -> TokenCreated:
    record, raw = await container.auth.create_api_token(user_id=user.id, name=body.name)
    return TokenCreated(id=record.id, name=record.name, token=raw)


@router.get("/tokens")
async def list_tokens(container: ContainerDep, _user: UserDep) -> list[TokenView]:
    return [
        TokenView(
            id=token.id,
            name=token.name,
            created_at=token.created_at,
            last_used_at=token.last_used_at,
        )
        for token in await container.auth.list_api_tokens()
    ]


@router.delete("/tokens/{token_id}", status_code=204)
async def delete_token(token_id: int, container: ContainerDep, _user: UserDep) -> None:
    if not await container.auth.delete_api_token(token_id):
        raise HTTPException(status_code=404, detail="токен не найден")
