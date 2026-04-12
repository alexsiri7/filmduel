"""Add tournaments and tournament_matches tables

Revision ID: 005
Revises: 004
Create Date: 2026-04-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tournaments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("filter_type", sa.Text(), nullable=True),
        sa.Column("filter_value", sa.Text(), nullable=True),
        sa.Column("bracket_size", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column(
            "champion_movie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("movies.id"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_tournaments_user_id", "tournaments", ["user_id"])

    op.create_table(
        "tournament_matches",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tournament_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tournaments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("round", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "movie_a_id",
            UUID(as_uuid=True),
            sa.ForeignKey("movies.id"),
            nullable=True,
        ),
        sa.Column(
            "movie_b_id",
            UUID(as_uuid=True),
            sa.ForeignKey("movies.id"),
            nullable=True,
        ),
        sa.Column(
            "winner_movie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("movies.id"),
            nullable=True,
        ),
        sa.Column(
            "duel_id",
            UUID(as_uuid=True),
            sa.ForeignKey("duels.id"),
            nullable=True,
        ),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tournament_id", "round", "position"),
    )
    op.create_index(
        "ix_tournament_matches_tournament_id",
        "tournament_matches",
        ["tournament_id"],
    )


def downgrade() -> None:
    op.drop_table("tournament_matches")
    op.drop_table("tournaments")
