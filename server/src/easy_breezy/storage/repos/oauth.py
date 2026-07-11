"""Репозиторий OAuth-провайдера: одноразовые коды и пары токенов (план §6)."""

from __future__ import annotations

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from easy_breezy.storage.models import OAuthCode, OAuthToken
from easy_breezy.storage.repos._util import rowcount


class OAuthRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- одноразовые коды -----------------------------------------------------

    async def create_code(
        self,
        *,
        code_hash: str,
        client_id: str,
        redirect_uri: str,
        user_id: int,
        expires_at: int,
    ) -> OAuthCode:
        code = OAuthCode(
            code_hash=code_hash,
            client_id=client_id,
            redirect_uri=redirect_uri,
            user_id=user_id,
            expires_at=expires_at,
        )
        self._session.add(code)
        await self._session.flush()
        return code

    async def consume_code(self, code_hash: str, *, now: int) -> OAuthCode | None:
        """Атомарно гасит код; повторное использование возвращает None."""
        result = await self._session.execute(
            select(OAuthCode).where(OAuthCode.code_hash == code_hash)
        )
        code = result.scalar_one_or_none()
        if code is None or code.used or code.expires_at <= now:
            return None
        code.used = True
        return code

    # --- пары access/refresh ----------------------------------------------------

    async def create_tokens(
        self,
        *,
        access_hash: str,
        refresh_hash: str,
        user_id: int,
        access_expires_at: int,
        refresh_expires_at: int,
    ) -> OAuthToken:
        token = OAuthToken(
            access_hash=access_hash,
            refresh_hash=refresh_hash,
            user_id=user_id,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
        )
        self._session.add(token)
        await self._session.flush()
        return token

    async def get_valid_by_access(
        self, access_hash: str, *, now: int
    ) -> OAuthToken | None:
        result = await self._session.execute(
            select(OAuthToken).where(
                OAuthToken.access_hash == access_hash,
                OAuthToken.revoked.is_(False),
                OAuthToken.access_expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def get_valid_by_refresh(
        self, refresh_hash: str, *, now: int
    ) -> OAuthToken | None:
        result = await self._session.execute(
            select(OAuthToken).where(
                OAuthToken.refresh_hash == refresh_hash,
                OAuthToken.revoked.is_(False),
                OAuthToken.refresh_expires_at > now,
            )
        )
        return result.scalar_one_or_none()

    async def revoke(self, token_id: int) -> None:
        await self._session.execute(
            update(OAuthToken).where(OAuthToken.id == token_id).values(revoked=True)
        )

    async def revoke_for_user(self, user_id: int) -> int:
        """Unlink: все пары пользователя становятся недействительными."""
        result = await self._session.execute(
            update(OAuthToken)
            .where(OAuthToken.user_id == user_id, OAuthToken.revoked.is_(False))
            .values(revoked=True)
        )
        return rowcount(result)

    async def purge_expired(self, *, now: int) -> int:
        """Чистка: протухшие коды и пары с истёкшим refresh."""
        codes = await self._session.execute(
            delete(OAuthCode).where(OAuthCode.expires_at <= now)
        )
        tokens = await self._session.execute(
            delete(OAuthToken).where(OAuthToken.refresh_expires_at <= now)
        )
        return rowcount(codes) + rowcount(tokens)
