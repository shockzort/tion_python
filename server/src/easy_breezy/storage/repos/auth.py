"""Репозитории авторизации: пользователи, сессии, api-токены.

В БД — только хэши токенов (sha256 opaque-значений) и argon2id паролей.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import ApiToken, AuthSession, User
from easy_breezy.storage.repos._util import rowcount


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count(self) -> int:
        result = await self._session.execute(select(func.count(User.id)))
        return result.scalar_one()

    async def create(
        self, *, username: str, password_hash: str, created_at: int
    ) -> User:
        user = User(
            username=username, password_hash=password_hash, created_at=created_at
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def get(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def first(self) -> User | None:
        """Первый (единственный в соло-сценарии) пользователь — владелец."""
        result = await self._session.execute(select(User).order_by(User.id).limit(1))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> User | None:
        result = await self._session.execute(
            select(User).where(User.username == username)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[User]:
        result = await self._session.execute(select(User).order_by(User.id))
        return list(result.scalars())

    async def delete(self, user: User) -> None:
        """Сессии/api-токены/oauth-записи уходят каскадом (FK CASCADE)."""
        await self._session.delete(user)


class SessionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, user_id: int, token_hash: str, created_at: int, expires_at: int
    ) -> AuthSession:
        auth_session = AuthSession(
            user_id=user_id,
            token_hash=token_hash,
            created_at=created_at,
            expires_at=expires_at,
        )
        self._session.add(auth_session)
        await self._session.flush()
        return auth_session

    async def get_valid(self, token_hash: str, *, now: int) -> AuthSession | None:
        result = await self._session.execute(
            select(AuthSession).where(
                AuthSession.token_hash == token_hash, AuthSession.expires_at > now
            )
        )
        return result.scalar_one_or_none()

    async def delete_by_hash(self, token_hash: str) -> None:
        await self._session.execute(
            delete(AuthSession).where(AuthSession.token_hash == token_hash)
        )

    async def delete_for_user(self, user_id: int) -> int:
        """Сброс всех сессий пользователя (смена пароля)."""
        result = await self._session.execute(
            delete(AuthSession).where(AuthSession.user_id == user_id)
        )
        return rowcount(result)

    async def purge_expired(self, *, now: int) -> int:
        result = await self._session.execute(
            delete(AuthSession).where(AuthSession.expires_at <= now)
        )
        return rowcount(result)


class ApiTokenRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self, *, name: str, user_id: int, token_hash: str, created_at: int
    ) -> ApiToken:
        token = ApiToken(
            name=name, user_id=user_id, token_hash=token_hash, created_at=created_at
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_by_hash(self, token_hash: str) -> ApiToken | None:
        result = await self._session.execute(
            select(ApiToken).where(ApiToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[ApiToken]:
        result = await self._session.execute(select(ApiToken).order_by(ApiToken.id))
        return list(result.scalars())

    async def delete(self, token_id: int) -> bool:
        result = await self._session.execute(
            delete(ApiToken).where(ApiToken.id == token_id)
        )
        return rowcount(result) > 0
