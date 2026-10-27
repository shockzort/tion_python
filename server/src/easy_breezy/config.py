"""Конфигурация сервиса: переменные окружения с префиксом EB_ и файл .env."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class XiaomiDeviceConfig(BaseModel):
    """Прибор Xiaomi: адрес в LAN и токен miIO (секрет — только в .env)."""

    did: int = Field(gt=0)
    """Идентификатор устройства в облаке Mi Home (он же id прибора в API)."""
    host: str = Field(min_length=1)
    token: SecretStr
    name: str = Field(min_length=1, max_length=100)
    model: str = "xiaomi.humidifier.ha2"

    @field_validator("token")
    @classmethod
    def _check_token(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value()
        if len(raw) != 32 or any(char not in "0123456789abcdefABCDEF" for char in raw):
            raise ValueError("токен miIO — 32 hex-символа")
        return value


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
    command_offline_grace_seconds: float = 180.0
    """Сколько команда ждёт возвращения бризера в эфир, прежде чем упасть.

    Полевой факт стенда: линк рвётся каждые несколько минут, а отказ выжигает
    ключ идемпотентности навсегда — без ожидания расписание теряет устройство.
    """
    timezone: str | None = None
    """IANA-таймзона расписаний (например, Europe/Moscow); None — системная."""

    # Датчики (Фаза 6); пустые значения — соответствующий источник выключен
    magicair_email: str | None = None
    magicair_password: str | None = None
    """Учётка приложения Tion MagicAir (облачный опрос CO₂-датчиков)."""
    mqtt_url: str | None = None
    """Брокер сторонних датчиков: mqtt://[user:pass@]host[:1883]."""
    xiaomi_devices: list[XiaomiDeviceConfig] = Field(default_factory=list)
    """Приборы Xiaomi по локальному miIO (JSON-список); пусто — интеграция выкл."""
    push_contact: str = "https://easy-breezy.duckdns.org"
    """VAPID sub-claim (контакт для пуш-сервисов): https-URL или mailto:."""
    command_wait_seconds: float = 5.0
    """Сколько REST ждёт итог команды синхронно (иначе 202 + WS)."""
    session_ttl_days: int = 30
    """Время жизни сессии-cookie."""
    session_cookie_secure: bool = False
    """Secure-флаг cookie; включается за TLS (nginx, Фаза 4)."""
    filter_reset_days: dict[str, Annotated[int, Field(ge=1, le=65535)] | None] = Field(
        default_factory=dict
    )
    """Проверенный ресурс после сброса S4, {uuid: дни}; пусто — функция закрыта.

    Это критерий контрольного чтения, не записываемое значение ресурса.
    Заполняется после аппаратной проверки при фактической замене фильтров.
    null разрешает полевую проверку без объявления успеха.
    """

    def resolved_database_url(self) -> str:
        """URL БД: явный или файл в каталоге данных."""
        if self.database_url is not None:
            return self.database_url
        return f"sqlite+aiosqlite:///{self.data_dir / 'easy_breezy.db'}"
