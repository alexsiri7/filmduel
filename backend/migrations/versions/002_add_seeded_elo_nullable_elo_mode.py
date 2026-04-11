"""Add seeded_elo, nullable elo, mode on duels

Revision ID: 002
Revises: 001
Create Date: 2026-04-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add seeded_elo column to user_movies
    op.add_column(
        "user_movies",
        sa.Column("seeded_elo", sa.Integer(), nullable=True),
    )

    # Make elo nullable and change default from 1000 to NULL
    op.alter_column(
        "user_movies",
        "elo",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=None,
    )

    # Drop old non-partial index, recreate as partial (WHERE elo IS NOT NULL)
    op.drop_index("ix_user_movies_user_elo", table_name="user_movies")
    op.execute(
        'CREATE INDEX ix_user_movies_user_elo ON user_movies (user_id, elo) '
        'WHERE elo IS NOT NULL'
    )

    # Add mode column to duels
    op.add_column(
        "duels",
        sa.Column("mode", sa.Text(), nullable=False, server_default="discovery"),
    )


def downgrade() -> None:
    # Remove mode from duels
    op.drop_column("duels", "mode")

    # Restore non-partial index
    op.drop_index("ix_user_movies_user_elo", table_name="user_movies")
    op.create_index("ix_user_movies_user_elo", "user_movies", ["user_id", "elo"])

    # Revert elo to non-nullable with default 1000
    op.execute("UPDATE user_movies SET elo = 1000 WHERE elo IS NULL")
    op.alter_column(
        "user_movies",
        "elo",
        existing_type=sa.Integer(),
        nullable=False,
        server_default="1000",
    )

    # Drop seeded_elo
    op.drop_column("user_movies", "seeded_elo")
