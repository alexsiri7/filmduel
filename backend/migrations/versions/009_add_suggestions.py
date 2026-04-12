"""Add suggestions table for AI-curated film recommendations

Revision ID: 009
Revises: 006, 007
Create Date: 2026-04-12
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "009"
down_revision: Union[str, Sequence[str]] = ("006", "007")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "suggestions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("movie_id", UUID(as_uuid=True), sa.ForeignKey("movies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("added_to_watchlist_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_suggestions_user_id", "suggestions", ["user_id"])
    op.create_index(
        "ix_suggestions_user_active",
        "suggestions",
        ["user_id", "dismissed_at"],
        postgresql_where=sa.text("dismissed_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_suggestions_user_active", table_name="suggestions")
    op.drop_index("ix_suggestions_user_id", table_name="suggestions")
    op.drop_table("suggestions")
