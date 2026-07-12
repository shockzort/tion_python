"""CLI ``breezy user``: add/list/passwd/remove напрямую через БД."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from argon2 import PasswordHasher
from sqlalchemy import func, select
from typer.testing import CliRunner

from easy_breezy.cli import app
from easy_breezy.storage import Database
from easy_breezy.storage.models import ApiToken, AuthSession, User

runner = CliRunner()


@pytest.fixture
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """CLI работает с БД в EB_DATA_DIR; .env стенда не должен вмешиваться."""
    monkeypatch.chdir(tmp_path)  # чтобы server/.env не подхватился
    monkeypatch.setenv("EB_DATA_DIR", str(tmp_path))
    return tmp_path


def db_of(data_dir: Path) -> Database:
    return Database(f"sqlite+aiosqlite:///{data_dir / 'easy_breezy.db'}")


async def fetch_users(data_dir: Path) -> list[User]:
    db = db_of(data_dir)
    try:
        await db.migrate()  # CLI мог выйти до создания схемы
        async with db.session() as session:
            result = await session.execute(select(User).order_by(User.id))
            users = list(result.scalars())
            session.expunge_all()
            return users
    finally:
        await db.dispose()


def test_add_list_passwd_remove_roundtrip(data_dir: Path) -> None:
    added = runner.invoke(app, ["user", "add", "alice"], input="secret123\nsecret123\n")
    assert added.exit_code == 0, added.output
    assert "создан" in added.output

    (user,) = asyncio.run(fetch_users(data_dir))
    assert user.username == "alice"
    PasswordHasher().verify(user.password_hash, "secret123")  # argon2id

    listed = runner.invoke(app, ["user", "list"])
    assert listed.exit_code == 0
    assert "alice" in listed.output

    # дубликат — ошибка с кодом 1
    duplicate = runner.invoke(
        app, ["user", "add", "alice"], input="secret123\nsecret123\n"
    )
    assert duplicate.exit_code == 1
    assert "уже существует" in duplicate.output

    # passwd меняет хэш и сбрасывает сессии
    async def seed_session_and_token(user_id: int) -> None:
        db = db_of(data_dir)
        try:
            async with db.session() as session:
                session.add(
                    AuthSession(
                        user_id=user_id,
                        token_hash="a" * 64,
                        created_at=0,
                        expires_at=2**31,
                    )
                )
                session.add(
                    ApiToken(
                        name="cli",
                        user_id=user_id,
                        token_hash="b" * 64,
                        created_at=0,
                    )
                )
        finally:
            await db.dispose()

    asyncio.run(seed_session_and_token(user.id))

    changed = runner.invoke(
        app, ["user", "passwd", "alice"], input="newsecret1\nnewsecret1\n"
    )
    assert changed.exit_code == 0, changed.output
    assert "сессий сброшено: 1" in changed.output
    (updated,) = asyncio.run(fetch_users(data_dir))
    PasswordHasher().verify(updated.password_hash, "newsecret1")

    # remove: подтверждение, каскад чистит api-токены
    removed = runner.invoke(app, ["user", "remove", "alice"], input="y\n")
    assert removed.exit_code == 0, removed.output
    assert "последний пользователь" in removed.output
    assert asyncio.run(fetch_users(data_dir)) == []

    async def count_leftovers() -> tuple[int, int]:
        db = db_of(data_dir)
        try:
            async with db.session() as session:
                sessions = (
                    await session.execute(select(func.count(AuthSession.id)))
                ).scalar_one()
                tokens = (
                    await session.execute(select(func.count(ApiToken.id)))
                ).scalar_one()
                return sessions, tokens
        finally:
            await db.dispose()

    assert asyncio.run(count_leftovers()) == (0, 0)


def test_short_password_rejected(data_dir: Path) -> None:
    result = runner.invoke(app, ["user", "add", "bob"], input="short\nshort\n")
    assert result.exit_code == 1
    assert "короче" in result.output
    assert asyncio.run(fetch_users(data_dir)) == []


def test_passwd_and_remove_unknown_user(data_dir: Path) -> None:
    runner.invoke(app, ["user", "list"])  # прогревает миграции
    missing = runner.invoke(
        app, ["user", "passwd", "ghost"], input="secret123\nsecret123\n"
    )
    assert missing.exit_code == 1
    assert "не найден" in missing.output
    removed = runner.invoke(app, ["user", "remove", "ghost"])
    assert removed.exit_code == 1
    assert "не найден" in removed.output
