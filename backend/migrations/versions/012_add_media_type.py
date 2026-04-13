"""Add media_type column to movies table for TV show support

Revision ID: 012
Revises: 011
Create Date: 2026-04-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add media_type column with server_default so existing rows get 'movie'
    op.add_column(
        "movies",
        sa.Column(
            "media_type",
            sa.Text(),
            nullable=False,
            server_default="movie",
        ),
    )
    op.create_index("ix_movies_media_type", "movies", ["media_type"])

    # Drop the old unique constraint on trakt_id alone
    op.drop_constraint("movies_trakt_id_key", "movies", type_="unique")

    # Add composite unique constraint on (trakt_id, media_type)
    op.create_unique_constraint(
        "uq_movies_trakt_id_media_type", "movies", ["trakt_id", "media_type"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_movies_trakt_id_media_type", "movies", type_="unique")
    op.create_unique_constraint("movies_trakt_id_key", "movies", ["trakt_id"])
    op.drop_index("ix_movies_media_type", table_name="movies")
    op.drop_column("movies", "media_type")
