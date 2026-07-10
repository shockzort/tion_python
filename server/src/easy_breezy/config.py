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
