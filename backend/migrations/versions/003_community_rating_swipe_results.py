"""Add community_rating to movies, create swipe_results table, index on user_movies

Revision ID: 003
Revises: 002
Create Date: 2026-04-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add community_rating column to movies
    op.add_column(
        "movies",
        sa.Column("community_rating", sa.Numeric(4, 1), nullable=True),
    )

    # 2. Create swipe_results table
    op.create_table(
        "swipe_results",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "movie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("movies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seen", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_swipe_results_user_id", "swipe_results", ["user_id"])

    # 3. Add partial index on user_movies(user_id, seen, battles) WHERE seen = true
    op.execute(
        "CREATE INDEX ix_user_movies_user_seen_battles "
        "ON user_movies (user_id, seen, battles) "
        "WHERE seen = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_user_movies_user_seen_battles")
    op.drop_index("ix_swipe_results_user_id", table_name="swipe_results")
    op.drop_table("swipe_results")
    op.drop_column("movies", "community_rating")
