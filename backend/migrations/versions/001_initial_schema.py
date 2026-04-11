"""Initial schema — users, movies, user_movies, duels

Revision ID: 001
Revises:
Create Date: 2026-04-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trakt_user_id", sa.Text(), unique=True, nullable=False),
        sa.Column("trakt_username", sa.Text(), nullable=False),
        sa.Column("trakt_access_token", sa.Text(), nullable=False),
        sa.Column("trakt_refresh_token", sa.Text(), nullable=False),
        sa.Column(
            "trakt_token_expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # Movies
    op.create_table(
        "movies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("trakt_id", sa.Integer(), unique=True, nullable=False),
        sa.Column("imdb_id", sa.Text(), nullable=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("genres", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("runtime", sa.Integer(), nullable=True),
        sa.Column("poster_url", sa.Text(), nullable=True),
        sa.Column(
            "cached_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    # User Movies (per-user movie state + ELO)
    op.create_table(
        "user_movies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "movie_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("movies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("seen", sa.Boolean(), nullable=True),
        sa.Column("elo", sa.Integer(), nullable=False, server_default="1000"),
        sa.Column("battles", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trakt_rating", sa.Integer(), nullable=True),
        sa.Column("last_dueled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "movie_id"),
    )
    op.create_index("ix_user_movies_user_id", "user_movies", ["user_id"])
    op.create_index("ix_user_movies_user_seen", "user_movies", ["user_id", "seen"])
    op.create_index("ix_user_movies_user_elo", "user_movies", ["user_id", "elo"])

    # Duels
    op.create_table(
        "duels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "winner_movie_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("movies.id"),
            nullable=True,
        ),
        sa.Column(
            "loser_movie_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("movies.id"),
            nullable=True,
        ),
        sa.Column("winner_elo_before", sa.Integer(), nullable=True),
        sa.Column("loser_elo_before", sa.Integer(), nullable=True),
        sa.Column("winner_elo_after", sa.Integer(), nullable=True),
        sa.Column("loser_elo_after", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_duels_user_id", "duels", ["user_id"])


def downgrade() -> None:
    op.drop_table("duels")
    op.drop_table("user_movies")
    op.drop_table("movies")
    op.drop_table("users")
