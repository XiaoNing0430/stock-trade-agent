"""计划关联与离场模式列

Revision ID: 3f9c2d7ab410
Revises: b099a3acfecd
Create Date: 2026-09-12 16:20:41.183402

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f9c2d7ab410"
down_revision: str | None = "b099a3acfecd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "trade_plans",
        sa.Column(
            "related_plan", sa.String(length=96), nullable=True, comment="交易对关联：sell→buy 计划 id（仅 sell 使用）"
        ),
    )
    op.add_column(
        "trade_plans",
        sa.Column(
            "exit_mode",
            sa.String(length=16),
            nullable=True,
            comment="交易对离场模式 race|sell_priority|sell_stop_only|sell_only；NULL≡race",
        ),
    )


def downgrade() -> None:
    op.drop_column("trade_plans", "exit_mode")
    op.drop_column("trade_plans", "related_plan")
