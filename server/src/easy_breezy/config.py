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
    ui_dist: Path = Path("../ui/dist")
    """Собранный UI (vite build); каталога нет — сервис работает API-only."""

    # Умный дом Яндекса (Фаза 4); пустые значения — интеграция выключена
    yandex_client_id: str | None = None
    yandex_client_secret: str | None = None
    yandex_redirect_uri: str = "https://social.yandex.net/broker/redirect"
    """Единственный допустимый redirect_uri линковки (брокер Яндекса)."""
    yandex_skill_id: str | None = None
    yandex_callback_token: str | None = None
    database_url: str | None = None
    """Явный URL БД; ``None`` — sqlite в ``data_dir/easy_breezy.db``."""
    fake_devices: int = 0
    """Dev-режим: сколько эмуляторов FakeS4 поднять вместо железа (0 — выкл)."""
    manual_hold_minutes: int = 60
    """Окно manual-hold после ручной команды (ADR-0005)."""
    timezone: str | None = None
    """IANA-таймзона расписаний (например, Europe/Moscow); None — системная."""

    # Датчики (Фаза 6); пустые значения — соответствующий источник выключен
    magicair_email: str | None = None
    magicair_password: str | None = None
    """Учётка приложения Tion MagicAir (облачный опрос CO₂-датчиков)."""
    mqtt_url: str | None = None
    """Брокер сторонних датчиков: mqtt://[user:pass@]host[:1883]."""
    command_wait_seconds: float = 5.0
    """Сколько REST ждёт итог команды синхронно (иначе 202 + WS)."""
    session_ttl_days: int = 30
    """Время жизни сессии-cookie."""
    session_cookie_secure: bool = False
    """Secure-флаг cookie; включается за TLS (nginx, Фаза 4)."""

    def resolved_database_url(self) -> str:
        """URL БД: явный или файл в каталоге данных."""
        if self.database_url is not None:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.data_dir / 'easy_breezy.db'}"
