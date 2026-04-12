"""Add AI-curated tournament fields

Revision ID: 008
Revises: 007
Create Date: 2026-04-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tournaments", sa.Column("tagline", sa.Text(), nullable=True))
    op.add_column("tournaments", sa.Column("theme_description", sa.Text(), nullable=True))
    op.add_column(
        "tournaments",
        sa.Column("is_ai_curated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column("tournaments", sa.Column("llm_response", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("tournaments", "llm_response")
    op.drop_column("tournaments", "is_ai_curated")
    op.drop_column("tournaments", "theme_description")
    op.drop_column("tournaments", "tagline")
