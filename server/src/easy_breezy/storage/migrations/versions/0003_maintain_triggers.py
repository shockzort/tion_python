"""maintain-триггеры: вид, диапазон скоростей, цели регулирования.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "triggers",
        sa.Column(
            "kind", sa.String(length=20), nullable=False, server_default="threshold"
        ),
    )
    op.add_column("triggers", sa.Column("speed_min", sa.Integer(), nullable=True))
    op.add_column("triggers", sa.Column("speed_max", sa.Integer(), nullable=True))
    op.add_column("triggers", sa.Column("targets", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("triggers") as batch:
        batch.drop_column("targets")
        batch.drop_column("speed_max")
        batch.drop_column("speed_min")
        batch.drop_column("kind")
