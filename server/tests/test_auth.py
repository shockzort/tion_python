"""Авторизация: setup-поток, логин/сессии, api-токены, троттлинг."""

from __future__ import annotations

import pytest

from easy_breezy.auth import AuthError, AuthService, SetupError, ThrottledError
from easy_breezy.storage import Database


class FakeNow:
    def __init__(self, value: float = 1_000_000.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


@pytest.fixture
def now() -> FakeNow:
    return FakeNow()


@pytest.fixture
def auth(db: Database, now: FakeNow) -> AuthService:
    return AuthService(db, session_ttl_seconds=3600, now=now)


async def make_admin(auth: AuthService) -> None:
    token = await auth.ensure_setup_token()
    assert token is not None
    await auth.create_admin(setup_token=token, username="admin", password="s3cret")


async def test_setup_flow(auth: AuthService) -> None:
    token = await auth.ensure_setup_token()
    assert token is not None

    with pytest.raises(SetupError):
        await auth.create_admin(
            setup_token="не тот", username="admin", password="s3cret"
        )

    user = await auth.create_admin(
        setup_token=token, username="admin", password="s3cret"
    )
    assert user.username == "admin"
    assert user.password_hash.startswith("$argon2id$")

    # настройка одноразовая: токена больше нет, повтор невозможен
    assert await auth.ensure_setup_token() is None
    with pytest.raises(SetupError):
        await auth.create_admin(setup_token=token, username="x", password="y")


async def test_login_session_logout(auth: AuthService, now: FakeNow) -> None:
    await make_admin(auth)

    with pytest.raises(AuthError):
        await auth.login("admin", "неверный")
    with pytest.raises(AuthError):
        await auth.login("нет такого", "s3cret")

    token, user = await auth.login("admin", "s3cret")
    resolved = await auth.session_user(token)
    assert resolved is not None and resolved.id == user.id
    assert await auth.session_user("чужой-токен") is None

    now.value += 3601  # TTL сессии истёк
    assert await auth.session_user(token) is None

    token2, _ = await auth.login("admin", "s3cret")
    await auth.logout(token2)
    assert await auth.session_user(token2) is None


async def test_login_throttled_after_failures(auth: AuthService, now: FakeNow) -> None:
    await make_admin(auth)
    for _ in range(5):
        with pytest.raises(AuthError):
            await auth.login("admin", "мимо")

    with pytest.raises(ThrottledError):
        await auth.login("admin", "s3cret")  # даже верный пароль в блоке

    now.value += 61  # окно блокировки прошло
    token, _ = await auth.login("admin", "s3cret")
    assert await auth.session_user(token) is not None


async def test_api_tokens(auth: AuthService) -> None:
    await make_admin(auth)
    _, user = await auth.login("admin", "s3cret")

    record, raw = await auth.create_api_token(user_id=user.id, name="cli")
    resolved = await auth.api_token_user(raw)
    assert resolved is not None and resolved.id == user.id

    tokens = await auth.list_api_tokens()
    assert [t.name for t in tokens] == ["cli"]
    assert record.token_hash != raw  # в БД только хэш

    assert await auth.delete_api_token(tokens[0].id)
    assert await auth.api_token_user(raw) is None
    assert not await auth.delete_api_token(tokens[0].id)
