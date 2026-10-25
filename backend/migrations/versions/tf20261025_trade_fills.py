"""trade fills ledger

Revision ID: tf20261025
Revises: c9edit20261003
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tf20261025"
down_revision: str | None = "c9edit20261003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trade_fills",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("client_request_id", sa.String(64), nullable=True),
        sa.Column("workspace_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("traded_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.String(96), nullable=True),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("voided_at_ms", sa.BigInteger(), nullable=True),
        sa.Column("void_reason", sa.String(200), nullable=True),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("client_request_id", name="uq_trade_fills_request_id"),
        sa.CheckConstraint("qty > 0", name="ck_trade_fills_qty_positive"),
        sa.CheckConstraint("direction IN ('buy','sell')", name="ck_trade_fills_direction"),
    )
    op.create_index("ix_trade_fills_workspace_id", "trade_fills", ["workspace_id"])
    op.create_index("ix_trade_fills_code", "trade_fills", ["code"])
    op.create_index("ix_trade_fills_traded_at_ms", "trade_fills", ["traded_at_ms"])
    op.create_index("ix_trade_fills_plan_id", "trade_fills", ["plan_id"])
    op.create_index("ix_trade_fills_ws_code_time", "trade_fills", ["workspace_id", "code", "traded_at_ms"])


def downgrade() -> None:
    op.drop_table("trade_fills")
