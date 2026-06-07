"""Add SIMKL provider fields and make Trakt fields nullable.

Revision ID: 019
Revises: 018
Create Date: 2026-06-07
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Make Trakt fields nullable (existing users keep their data)
    op.alter_column("users", "trakt_user_id", nullable=True)
    op.alter_column("users", "trakt_username", nullable=True)
    op.alter_column("users", "trakt_access_token", nullable=True)
    op.alter_column("users", "trakt_refresh_token", nullable=True)
    op.alter_column("users", "trakt_token_expires_at", nullable=True)

    # Add SIMKL fields
    op.add_column("users", sa.Column("simkl_user_id", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_users_simkl_user_id", "users", ["simkl_user_id"])
    op.add_column("users", sa.Column("simkl_username", sa.Text(), nullable=True))
    op.add_column(
        "users", sa.Column("simkl_access_token", sa.Text(), nullable=True)
    )
    op.add_column(
        "users", sa.Column("simkl_refresh_token", sa.Text(), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column("simkl_token_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "sync_ratings_to_simkl",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    # Add simkl_id to movies for correct ID tracking (avoids trakt_id collision)
    op.add_column("movies", sa.Column("simkl_id", sa.Integer(), nullable=True))
    op.create_index("ix_movies_simkl_id", "movies", ["simkl_id"])


def downgrade() -> None:
    # NOTE: Cannot safely restore nullable=False on Trakt columns if SIMKL-only
    # users exist (their trakt_* fields are NULL). Downgrade is not safe once
    # any SIMKL-only user has registered. Manual data cleanup required.
    op.drop_index("ix_movies_simkl_id", table_name="movies")
    op.drop_column("movies", "simkl_id")
    op.drop_column("users", "sync_ratings_to_simkl")
    op.drop_column("users", "simkl_token_expires_at")
    op.drop_column("users", "simkl_refresh_token")
    op.drop_column("users", "simkl_access_token")
    op.drop_column("users", "simkl_username")
    op.drop_constraint("uq_users_simkl_user_id", "users", type_="unique")
    op.drop_column("users", "simkl_user_id")
    op.alter_column("users", "trakt_token_expires_at", nullable=False)
    op.alter_column("users", "trakt_refresh_token", nullable=False)
    op.alter_column("users", "trakt_access_token", nullable=False)
    op.alter_column("users", "trakt_username", nullable=False)
    op.alter_column("users", "trakt_user_id", nullable=False)
