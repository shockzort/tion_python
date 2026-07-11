"""Конфигурация сервиса: переменные окружения с префиксом EB_ и файл .env."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки процесса.

    Значения берутся из окружения (префикс ``EB_``) и файла ``.env``.
    Секреты и параметры интеграций добавляются в своих фазах.
    """

    model_config = SettingsConfigDict(
        env_prefix="EB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"  # домашний сервис слушает LAN
    port: int = 8000
    log_level: str = "INFO"
    log_dir: Path | None = None
    """Каталог логов; ``None`` — только stdout (journald)."""
    data_dir: Path = Path("data")
    """Каталог данных (БД, бэкапы)."""
    database_url: str | None = None
    """Явный URL БД; ``None`` — sqlite в ``data_dir/easy_breezy.db``."""
    fake_devices: int = 0
    """Dev-режим: сколько эмуляторов FakeS4 поднять вместо железа (0 — выкл)."""
    manual_hold_minutes: int = 60
    """Окно manual-hold после ручной команды (ADR-0005)."""
    command_wait_seconds: float = 5.0
    """Сколько REST ждёт итог команды синхронно (иначе 202 + WS)."""
    session_ttl_days: int = 30
    """Время жизни сессии-cookie."""

    def resolved_database_url(self) -> str:
        """URL БД: явный или файл в каталоге данных."""
        if self.database_url is not None:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.data_dir / 'easy_breezy.db'}"
