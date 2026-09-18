"""P3 point-in-time daily snapshots

Revision ID: p3pit20260918
Revises: a7e4c19d5b30
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "p3pit20260918"
down_revision = "a7e4c19d5b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table(
        "snapshot_runs",
        sa.Column("as_of_date", sa.String(16), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="failed"),
        sa.Column("source", sa.String(64), nullable=False, server_default=""),
        sa.Column("error", sa.String(2000), nullable=True),
        sa.Column("universe_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bar_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("industry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suspended_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("coverage_pct", sa.Float(), nullable=True),
        sa.Column("degraded_reason", sa.String(2000), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "snapshot_closes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("as_of_date", sa.String(16), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Float(), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("trade_date", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="trading"),
        sa.Column("trade_status", sa.String(16), nullable=False, server_default="trading"),
        sa.Column("prev_close", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False, server_default="eastmoney"),
        sa.Column("acquisition", sa.String(32), nullable=False, server_default="realtime"),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("as_of_date", "code", name="uq_snapshot_closes_date_code"),
    )
    op.create_index("ix_snapshot_closes_as_of_date", "snapshot_closes", ["as_of_date"])
    op.create_index("ix_snapshot_closes_code", "snapshot_closes", ["code"])
    op.create_table(
        "snapshot_industries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("as_of_date", sa.String(16), nullable=False),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("provider", sa.String(64), nullable=False, server_default=""),
        sa.Column("acquisition", sa.String(32), nullable=False, server_default="realtime"),
        sa.Column("pit_quality", sa.String(16), nullable=False, server_default="exact"),
        sa.Column("observed_date", sa.String(16), nullable=True),
        sa.UniqueConstraint("as_of_date", "code", name="uq_snapshot_industries_date_code"),
    )
    op.create_index("ix_snapshot_industries_as_of_date", "snapshot_industries", ["as_of_date"])
    op.create_index("ix_snapshot_industries_code", "snapshot_industries", ["code"])
    op.create_table(
        "snapshot_audits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("as_of_date", sa.String(16), nullable=False),
        sa.Column("mode", sa.String(16), nullable=False, server_default="backfill"),
        sa.Column("canonical_hash", sa.String(64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("operator", sa.String(64), nullable=False, server_default="local"),
        sa.Column("action", sa.String(32), nullable=False, server_default="backfill"),
        sa.Column("reason", sa.String(2000), nullable=True),
        sa.Column("before_summary", sa.JSON(), nullable=True),
        sa.Column("after_summary", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_snapshot_audits_as_of_date", "snapshot_audits", ["as_of_date"])
    op.create_index("ix_snapshot_audits_canonical_hash", "snapshot_audits", ["canonical_hash"])
    op.create_unique_constraint(
        "uq_snapshot_audits_operation_content",
        "snapshot_audits",
        ["operator", "as_of_date", "action", "mode", "canonical_hash"],
    )

def downgrade() -> None:
    op.drop_constraint("uq_snapshot_audits_operation_content", "snapshot_audits", type_="unique")
    op.drop_table("snapshot_audits")
    op.drop_table("snapshot_industries")
    op.drop_table("snapshot_closes")
    op.drop_table("snapshot_runs")
