"""Add pool_expansions table for tracking background pool expansion runs

Revision ID: 006
Revises: 005
Create Date: 2026-04-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "pool_expansions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=True),
        sa.Column("films_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "ran_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_pool_expansions_user_source_key",
        "pool_expansions",
        ["user_id", "source", "source_key"],
    )


def downgrade() -> None:
    op.drop_table("pool_expansions")
