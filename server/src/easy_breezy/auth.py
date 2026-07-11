"""Авторизация: argon2id-пароли, opaque-токены (sha256), сессии (план §12).

Первый старт без пользователей печатает в лог setup-токен; им создаётся
локальный админ. Сессии и api-токены — случайные opaque-значения, в БД
хранятся только их sha256-хэши. Argon2 CPU-bound — считается в потоке.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from collections.abc import Callable

import structlog
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from easy_breezy.storage import Database
from easy_breezy.storage.models import ApiToken, User
from easy_breezy.storage.repos import ApiTokenRepo, SessionRepo, UserRepo

log = structlog.get_logger(__name__)

SESSION_COOKIE = "eb_session"

_THROTTLE_MAX_FAILS = 5
_THROTTLE_LOCK_SECONDS = 60.0


class AuthError(Exception):
    """Неверные учётные данные или недействительный токен."""


class SetupError(Exception):
    """Первичная настройка невозможна (уже выполнена или токен неверен)."""


class ThrottledError(Exception):
    """Слишком много неудачных попыток — подождите."""


def hash_token(token: str) -> str:
    """sha256-хэш opaque-токена (сессии, api, oauth)."""
    return hashlib.sha256(token.encode()).hexdigest()


class _LoginThrottle:
    """Троттлинг логина: N неудач подряд — блокировка на окно."""

    def __init__(self, now: Callable[[], float]) -> None:
        self._now = now
        self._fails: dict[str, int] = {}
        self._locked_until: dict[str, float] = {}

    def check(self, username: str) -> None:
        locked_until = self._locked_until.get(username)
        if locked_until is not None and locked_until > self._now():
            raise ThrottledError(
                f"слишком много попыток, подождите {_THROTTLE_LOCK_SECONDS:.0f} с"
            )

    def register_failure(self, username: str) -> None:
        fails = self._fails.get(username, 0) + 1
        self._fails[username] = fails
        if fails >= _THROTTLE_MAX_FAILS:
            self._locked_until[username] = self._now() + _THROTTLE_LOCK_SECONDS
            self._fails[username] = 0
            log.warning("login_throttled", username=username)

    def register_success(self, username: str) -> None:
        self._fails.pop(username, None)
        self._locked_until.pop(username, None)


class AuthService:
    def __init__(
        self,
        db: Database,
        *,
        session_ttl_seconds: int = 30 * 86400,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._db = db
        self._session_ttl = session_ttl_seconds
        self._now = now
        self._hasher = PasswordHasher()  # argon2id по умолчанию
        self._throttle = _LoginThrottle(now)
        self._setup_token: str | None = None
        # фиктивный хэш выравнивает время ответа для несуществующих логинов
        self._dummy_hash = self._hasher.hash(secrets.token_urlsafe(8))

    # --- первичная настройка -------------------------------------------------

    @property
    def setup_token(self) -> str | None:
        """Активный setup-токен; есть только пока не создан администратор."""
        return self._setup_token

    async def ensure_setup_token(self) -> str | None:
        """Нет пользователей — генерирует setup-токен и пишет его в лог."""
        async with self._db.session() as session:
            users = await UserRepo(session).count()
        if users:
            return None
        self._setup_token = secrets.token_urlsafe(16)
        log.warning(
            "setup_required",
            setup_token=self._setup_token,
            hint="POST /api/auth/setup {setup_token, username, password}",
        )
        return self._setup_token

    async def create_admin(
        self, *, setup_token: str, username: str, password: str
    ) -> User:
        """Создаёт первого администратора по setup-токену из лога."""
        expected = self._setup_token
        if expected is None or not secrets.compare_digest(
            setup_token.encode(), expected.encode()
        ):
            raise SetupError("setup-токен неверен или настройка уже выполнена")
        password_hash = await asyncio.to_thread(self._hasher.hash, password)
        async with self._db.session() as session:
            repo = UserRepo(session)
            if await repo.count():
                raise SetupError("пользователь уже создан")
            user = await repo.create(
                username=username,
                password_hash=password_hash,
                created_at=int(self._now()),
            )
        self._setup_token = None
        log.info("admin_created", username=username)
        return user

    # --- сессии ---------------------------------------------------------------

    async def login(self, username: str, password: str) -> tuple[str, User]:
        """Проверяет пару логин/пароль, возвращает (session-токен, пользователь)."""
        self._throttle.check(username)
        async with self._db.session() as session:
            user = await UserRepo(session).get_by_username(username)
        stored_hash = user.password_hash if user is not None else self._dummy_hash
        if not await self._verify_password(stored_hash, password) or user is None:
            self._throttle.register_failure(username)
            raise AuthError("неверный логин или пароль")
        self._throttle.register_success(username)

        token = secrets.token_urlsafe(32)
        now = int(self._now())
        async with self._db.session() as session:
            repo = SessionRepo(session)
            await repo.purge_expired(now=now)
            await repo.create(
                user_id=user.id,
                token_hash=hash_token(token),
                created_at=now,
                expires_at=now + self._session_ttl,
            )
        log.info("login_ok", username=username)
        return token, user

    async def logout(self, token: str) -> None:
        async with self._db.session() as session:
            await SessionRepo(session).delete_by_hash(hash_token(token))

    async def session_user(self, token: str) -> User | None:
        """Пользователь по session-cookie; продлевает last_used_at."""
        now = int(self._now())
        async with self._db.session() as session:
            auth_session = await SessionRepo(session).get_valid(
                hash_token(token), now=now
            )
            if auth_session is None:
                return None
            auth_session.last_used_at = now
            return await UserRepo(session).get(auth_session.user_id)

    # --- api-токены -----------------------------------------------------------

    async def create_api_token(
        self, *, user_id: int, name: str
    ) -> tuple[ApiToken, str]:
        """Создаёт токен для CLI/скриптов; сырое значение видно только сейчас."""
        token = secrets.token_urlsafe(32)
        async with self._db.session() as session:
            record = await ApiTokenRepo(session).create(
                name=name,
                user_id=user_id,
                token_hash=hash_token(token),
                created_at=int(self._now()),
            )
        return record, token

    async def api_token_user(self, token: str) -> User | None:
        async with self._db.session() as session:
            repo = ApiTokenRepo(session)
            record = await repo.get_by_hash(hash_token(token))
            if record is None:
                return None
            record.last_used_at = int(self._now())
            return await UserRepo(session).get(record.user_id)

    async def list_api_tokens(self) -> list[ApiToken]:
        async with self._db.session() as session:
            return await ApiTokenRepo(session).list_all()

    async def delete_api_token(self, token_id: int) -> bool:
        async with self._db.session() as session:
            return await ApiTokenRepo(session).delete(token_id)

    async def _verify_password(self, password_hash: str, password: str) -> bool:
        try:
            return await asyncio.to_thread(self._hasher.verify, password_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
