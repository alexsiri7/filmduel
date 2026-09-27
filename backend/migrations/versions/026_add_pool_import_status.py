"""Add pool import progress columns to users.

Revision ID: 026
Revises: 025
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "026"
down_revision: Union[str, None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("pool_import_status", sa.Text(), nullable=True))
    op.add_column(
        "users",
        sa.Column("pool_import_started_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "pool_import_started_at")
    op.drop_column("users", "pool_import_status")
