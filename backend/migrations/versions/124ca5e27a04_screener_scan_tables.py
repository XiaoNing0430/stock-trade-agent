"""screener scan tables

Revision ID: 124ca5e27a04
Revises: c1a08e78583e
Create Date: 2026-09-08 19:53:38.846506

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "124ca5e27a04"
down_revision: str | None = "c1a08e78583e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "screener_scan_configs",
        sa.Column("id", sa.String(length=96), nullable=False),
        sa.Column("workspace_id", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=16), nullable=True),
        sa.Column("last_hits", sa.JSON(), nullable=True),
        sa.Column("last_new_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_screener_scan_configs_workspace_id"), "screener_scan_configs", ["workspace_id"], unique=False
    )
    op.create_table(
        "screener_scan_history",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("strategy_id", sa.String(length=96), nullable=False),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False),
        sa.Column("new_count", sa.Integer(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_screener_scan_history_run_at"), "screener_scan_history", ["run_at"], unique=False)
    op.create_index(
        op.f("ix_screener_scan_history_strategy_id"), "screener_scan_history", ["strategy_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_screener_scan_history_strategy_id"), table_name="screener_scan_history")
    op.drop_index(op.f("ix_screener_scan_history_run_at"), table_name="screener_scan_history")
    op.drop_table("screener_scan_history")
    op.drop_index(op.f("ix_screener_scan_configs_workspace_id"), table_name="screener_scan_configs")
    op.drop_table("screener_scan_configs")
