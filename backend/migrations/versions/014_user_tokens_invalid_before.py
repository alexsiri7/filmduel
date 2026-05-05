"""Add tokens_invalid_before to users for JWT revocation on logout.

Revision ID: 014
Revises: 013
Create Date: 2026-05-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "tokens_invalid_before",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default="1970-01-01T00:00:00+00:00",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "tokens_invalid_before")
