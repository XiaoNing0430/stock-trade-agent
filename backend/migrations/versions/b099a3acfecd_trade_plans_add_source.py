"""trade_plans add source

Revision ID: b099a3acfecd
Revises: 124ca5e27a04
Create Date: 2026-09-10 21:42:16.522252

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b099a3acfecd"
down_revision: str | None = "124ca5e27a04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("trade_plans", sa.Column("source", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("trade_plans", "source")
