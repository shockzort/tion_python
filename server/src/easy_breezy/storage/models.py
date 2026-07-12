"""Модели БД — план §5.

Соглашения: времена — unix UTC (секунды, int); JSON — нативный тип SQLite;
удаление устройств — мягкое (``deleted_at``), журнал и телеметрия сохраняют
целостность. Словарь статусов/источников команд живёт здесь же — это факт
модели данных, а не логики.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON

_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class CommandSource(StrEnum):
    """Источник команды; определяет приоритет по умолчанию."""

    UI = "ui"
    YANDEX = "yandex"
    SCHEDULE = "schedule"
    TRIGGER = "trigger"
    SCENARIO = "scenario"
    INTENT = "intent"
    CLI = "cli"


class CommandStatus(StrEnum):
    """Жизненный цикл команды в журнале (план §8)."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    TIMEOUT = "timeout"
    SUPERSEDED = "superseded"
    SKIPPED_HOLD = "skipped_hold"


class Base(DeclarativeBase):
    """База моделей: naming convention (batch-миграции SQLite) + JSON-типы."""

    metadata = MetaData(naming_convention=_NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 — контракт SQLAlchemy
        dict[str, Any]: JSON,
        list[Any]: JSON,
    }


class Room(Base):
    __tablename__ = "rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Device(Base):
    __tablename__ = "devices"

    uuid: Mapped[str] = mapped_column(String(32), primary_key=True)
    mac: Mapped[str] = mapped_column(String(17), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    model: Mapped[str] = mapped_column(String(20), default="s4")
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), default=None
    )
    paired: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[int]
    deleted_at: Mapped[int | None] = mapped_column(default=None)
    """Мягкое удаление: журнал/телеметрия ссылаются на устройство вечно."""


class DeviceGroup(Base):
    __tablename__ = "device_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class DeviceGroupMember(Base):
    __tablename__ = "device_group_members"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("device_groups.id", ondelete="CASCADE"), primary_key=True
    )
    device_uuid: Mapped[str] = mapped_column(
        ForeignKey("devices.uuid", ondelete="CASCADE"), primary_key=True
    )


class CommandRecord(Base):
    """Журнал команд: идемпотентность, приоритеты, итог (план §8)."""

    __tablename__ = "commands"
    __table_args__ = (Index("ix_commands_device_created", "device_uuid", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    device_uuid: Mapped[str] = mapped_column(
        ForeignKey("devices.uuid", ondelete="CASCADE")
    )
    source: Mapped[str] = mapped_column(String(20))
    priority: Mapped[int]
    """0 — ручное (UI/Алиса/CLI/интент), 1 — триггер, 2 — расписание."""
    payload: Mapped[dict[str, Any]]
    """Дельта состояния (частичные поля S4State)."""
    status: Mapped[str] = mapped_column(String(20), default=CommandStatus.PENDING)
    result_state: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(String(500), default=None)
    created_at: Mapped[int]
    started_at: Mapped[int | None] = mapped_column(default=None)
    finished_at: Mapped[int | None] = mapped_column(default=None)


class Scenario(Base):
    __tablename__ = "scenarios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    actions: Mapped[list[Any]]
    """Список действий: {target: device|group, delta: {...}}."""


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    cron: Mapped[str] = mapped_column(String(100))
    scenario_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenarios.id", ondelete="CASCADE"), default=None
    )
    actions: Mapped[list[Any] | None] = mapped_column(default=None)
    """XOR со scenario_id: либо сценарий, либо inline-действия."""
    enabled: Mapped[bool] = mapped_column(default=True)
    cursor_ts: Mapped[int | None] = mapped_column(default=None)
    """Курсор планировщика: докуда обработана ось времени (unix).

    None — расписание ещё не видано планировщиком (курсор станет «сейчас»,
    прошлое не догоняется). Факт срабатывания фиксирует журнал команд.
    """


class Trigger(Base):
    """Триггер автоматизации; поведение определяет ``kind``.

    ``threshold`` — пороговая защёлка (enter/exit по ``op``/``threshold``).
    ``maintain`` — поддержание CO₂: ``threshold`` = целевой ppm,
    ``hysteresis`` = зона покоя, ``cooldown_s`` = минимум секунд между
    корректировками, ``last_fired_at`` = время последней корректировки;
    ``op``/``enter_*``/``exit_*``/``is_active`` не используются
    (``op`` хранится как ``>`` для NOT NULL).
    """

    __tablename__ = "triggers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    sensor_id: Mapped[int] = mapped_column(ForeignKey("sensors.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(30))
    op: Mapped[str] = mapped_column(String(2))
    threshold: Mapped[float]
    hysteresis: Mapped[float] = mapped_column(default=0.0)
    cooldown_s: Mapped[int] = mapped_column(default=0)
    kind: Mapped[str] = mapped_column(String(20), default="threshold")
    """threshold — защёлка по порогу; maintain — поддержание CO₂ у цели."""
    speed_min: Mapped[int | None] = mapped_column(default=None)
    """Нижняя граница диапазона (0 — регулятору разрешено выключать бризер)."""
    speed_max: Mapped[int | None] = mapped_column(default=None)
    """Верхняя граница диапазона скоростей (1..6), только для maintain."""
    targets: Mapped[list[Any] | None] = mapped_column(default=None)
    """Цели регулирования maintain: [{target_type: device|group, target_id}]."""
    window_start: Mapped[str | None] = mapped_column(String(5), default=None)
    window_end: Mapped[str | None] = mapped_column(String(5), default=None)
    enter_scenario_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenarios.id", ondelete="SET NULL"), default=None
    )
    enter_actions: Mapped[list[Any] | None] = mapped_column(default=None)
    exit_scenario_id: Mapped[int | None] = mapped_column(
        ForeignKey("scenarios.id", ondelete="SET NULL"), default=None
    )
    exit_actions: Mapped[list[Any] | None] = mapped_column(default=None)
    enabled: Mapped[bool] = mapped_column(default=True)
    is_active: Mapped[bool] = mapped_column(default=False)
    """Защёлка: True между enter и exit."""
    last_fired_at: Mapped[int | None] = mapped_column(default=None)


class Sensor(Base):
    __tablename__ = "sensors"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))
    """magicair | mqtt."""
    name: Mapped[str] = mapped_column(String(100))
    source_key: Mapped[str] = mapped_column(String(200), unique=True)
    room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), default=None
    )
    last_values: Mapped[dict[str, Any] | None] = mapped_column(default=None)
    last_seen_at: Mapped[int | None] = mapped_column(default=None)


class TelemetryRaw(Base):
    """Сырые точки (ретенция 7 дней, ежечасный downsample)."""

    __tablename__ = "telemetry_raw"
    __table_args__ = (
        Index("ix_telemetry_raw_series", "source_type", "source_id", "metric", "ts"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ts: Mapped[int] = mapped_column(index=True)
    source_type: Mapped[str] = mapped_column(String(10))
    """device | sensor."""
    source_id: Mapped[str] = mapped_column(String(50))
    metric: Mapped[str] = mapped_column(String(30))
    value: Mapped[float]


class TelemetryHourly(Base):
    """Часовые агрегаты (ретенция 2 года)."""

    __tablename__ = "telemetry_hourly"

    hour_ts: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(String(10), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    metric: Mapped[str] = mapped_column(String(30), primary_key=True)
    value_min: Mapped[float]
    value_max: Mapped[float]
    value_avg: Mapped[float]
    samples: Mapped[int]


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    """argon2id."""
    created_at: Mapped[int]


class AuthSession(Base):
    """Сессия браузера: opaque-cookie, в БД только sha256-хэш токена."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[int]
    expires_at: Mapped[int]
    last_used_at: Mapped[int | None] = mapped_column(default=None)


class ApiToken(Base):
    """Долгоживущий токен для CLI/скриптов; в БД только хэш."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[int]
    last_used_at: Mapped[int | None] = mapped_column(default=None)


class OAuthCode(Base):
    """Одноразовый код авторизации Яндекса (TTL 10 мин), хранится хэш."""

    __tablename__ = "oauth_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    client_id: Mapped[str] = mapped_column(String(100))
    redirect_uri: Mapped[str] = mapped_column(String(500))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[int]
    used: Mapped[bool] = mapped_column(default=False)


class OAuthToken(Base):
    """Пара access/refresh нашего OAuth-провайдера (хэши, TTL 1 ч / 1 г)."""

    __tablename__ = "oauth_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    access_hash: Mapped[str] = mapped_column(String(64), unique=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    access_expires_at: Mapped[int]
    refresh_expires_at: Mapped[int]
    revoked: Mapped[bool] = mapped_column(default=False)


class Setting(Base):
    """Настройки key/value (JSON-значение произвольной формы)."""

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    endpoint: Mapped[str] = mapped_column(String(500), unique=True)
    keys: Mapped[dict[str, Any]]
    created_at: Mapped[int]
