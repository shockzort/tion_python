"""initial schema.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "device_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_groups")),
        sa.UniqueConstraint("name", name=op.f("uq_device_groups_name")),
    )
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("endpoint", sa.String(length=500), nullable=False),
        sa.Column("keys", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_push_subscriptions")),
        sa.UniqueConstraint("endpoint", name=op.f("uq_push_subscriptions_endpoint")),
    )
    op.create_table(
        "rooms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rooms")),
        sa.UniqueConstraint("name", name=op.f("uq_rooms_name")),
    )
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("actions", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenarios")),
        sa.UniqueConstraint("name", name=op.f("uq_scenarios_name")),
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_settings")),
    )
    op.create_table(
        "telemetry_hourly",
        sa.Column("hour_ts", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=10), nullable=False),
        sa.Column("source_id", sa.String(length=50), nullable=False),
        sa.Column("metric", sa.String(length=30), nullable=False),
        sa.Column("value_min", sa.Float(), nullable=False),
        sa.Column("value_max", sa.Float(), nullable=False),
        sa.Column("value_avg", sa.Float(), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint(
            "hour_ts",
            "source_type",
            "source_id",
            "metric",
            name=op.f("pk_telemetry_hourly"),
        ),
    )
    op.create_table(
        "telemetry_raw",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=10), nullable=False),
        sa.Column("source_id", sa.String(length=50), nullable=False),
        sa.Column("metric", sa.String(length=30), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telemetry_raw")),
    )
    with op.batch_alter_table("telemetry_raw", schema=None) as batch_op:
        batch_op.create_index(
            "ix_telemetry_raw_series",
            ["source_type", "source_id", "metric", "ts"],
            unique=False,
        )
        batch_op.create_index(batch_op.f("ix_telemetry_raw_ts"), ["ts"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("password_hash", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("username", name=op.f("uq_users_username")),
    )
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_api_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_tokens")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_api_tokens_token_hash")),
    )
    op.create_table(
        "devices",
        sa.Column("uuid", sa.String(length=32), nullable=False),
        sa.Column("mac", sa.String(length=17), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("model", sa.String(length=20), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=True),
        sa.Column("paired", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("deleted_at", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
            name=op.f("fk_devices_room_id_rooms"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("uuid", name=op.f("pk_devices")),
        sa.UniqueConstraint("mac", name=op.f("uq_devices_mac")),
    )
    op.create_table(
        "oauth_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=100), nullable=False),
        sa.Column("redirect_uri", sa.String(length=500), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_codes")),
        sa.UniqueConstraint("code_hash", name=op.f("uq_oauth_codes_code_hash")),
    )
    op.create_table(
        "oauth_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("access_hash", sa.String(length=64), nullable=False),
        sa.Column("refresh_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("access_expires_at", sa.Integer(), nullable=False),
        sa.Column("refresh_expires_at", sa.Integer(), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_tokens")),
        sa.UniqueConstraint("access_hash", name=op.f("uq_oauth_tokens_access_hash")),
        sa.UniqueConstraint("refresh_hash", name=op.f("uq_oauth_tokens_refresh_hash")),
    )
    op.create_table(
        "schedules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("cron", sa.String(length=100), nullable=False),
        sa.Column("scenario_id", sa.Integer(), nullable=True),
        sa.Column("actions", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["scenario_id"],
            ["scenarios.id"],
            name=op.f("fk_schedules_scenario_id_scenarios"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
    )
    op.create_table(
        "sensors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("source_key", sa.String(length=200), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=True),
        sa.Column("last_values", sa.JSON(), nullable=True),
        sa.Column("last_seen_at", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["rooms.id"],
            name=op.f("fk_sensors_room_id_rooms"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sensors")),
        sa.UniqueConstraint("source_key", name=op.f("uq_sensors_source_key")),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
    )
    op.create_table(
        "commands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("device_uuid", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("result_state", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.Integer(), nullable=True),
        sa.Column("finished_at", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["device_uuid"],
            ["devices.uuid"],
            name=op.f("fk_commands_device_uuid_devices"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commands")),
        sa.UniqueConstraint(
            "idempotency_key", name=op.f("uq_commands_idempotency_key")
        ),
    )
    with op.batch_alter_table("commands", schema=None) as batch_op:
        batch_op.create_index(
            "ix_commands_device_created", ["device_uuid", "created_at"], unique=False
        )

    op.create_table(
        "device_group_members",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("device_uuid", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["device_uuid"],
            ["devices.uuid"],
            name=op.f("fk_device_group_members_device_uuid_devices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"],
            ["device_groups.id"],
            name=op.f("fk_device_group_members_group_id_device_groups"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "group_id", "device_uuid", name=op.f("pk_device_group_members")
        ),
    )
    op.create_table(
        "triggers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("sensor_id", sa.Integer(), nullable=False),
        sa.Column("metric", sa.String(length=30), nullable=False),
        sa.Column("op", sa.String(length=2), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("hysteresis", sa.Float(), nullable=False),
        sa.Column("cooldown_s", sa.Integer(), nullable=False),
        sa.Column("window_start", sa.String(length=5), nullable=True),
        sa.Column("window_end", sa.String(length=5), nullable=True),
        sa.Column("enter_scenario_id", sa.Integer(), nullable=True),
        sa.Column("enter_actions", sa.JSON(), nullable=True),
        sa.Column("exit_scenario_id", sa.Integer(), nullable=True),
        sa.Column("exit_actions", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_fired_at", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["enter_scenario_id"],
            ["scenarios.id"],
            name=op.f("fk_triggers_enter_scenario_id_scenarios"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["exit_scenario_id"],
            ["scenarios.id"],
            name=op.f("fk_triggers_exit_scenario_id_scenarios"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["sensor_id"],
            ["sensors.id"],
            name=op.f("fk_triggers_sensor_id_sensors"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_triggers")),
    )


def downgrade() -> None:
    op.drop_table("triggers")
    op.drop_table("device_group_members")
    with op.batch_alter_table("commands", schema=None) as batch_op:
        batch_op.drop_index("ix_commands_device_created")

    op.drop_table("commands")
    op.drop_table("sessions")
    op.drop_table("sensors")
    op.drop_table("schedules")
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_codes")
    op.drop_table("devices")
    op.drop_table("api_tokens")
    op.drop_table("users")
    with op.batch_alter_table("telemetry_raw", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_telemetry_raw_ts"))
        batch_op.drop_index("ix_telemetry_raw_series")

    op.drop_table("telemetry_raw")
    op.drop_table("telemetry_hourly")
    op.drop_table("settings")
    op.drop_table("scenarios")
    op.drop_table("rooms")
    op.drop_table("push_subscriptions")
    op.drop_table("device_groups")
