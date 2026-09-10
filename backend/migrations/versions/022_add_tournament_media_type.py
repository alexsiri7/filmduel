"""Add media_type column to tournaments so regeneration reuses the same pool

Revision ID: 022
Revises: 021
Create Date: 2026-09-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tournaments",
        sa.Column(
            "media_type",
            sa.Text(),
            nullable=False,
            server_default="movie",
        ),
    )

    # Every tournament was seeded from a single-media-type pool, so the first
    # bracket film records the media_type it was created over. Tournaments with
    # no joinable bracket film keep the 'movie' default.
    op.execute(
        sa.text(
            """
            UPDATE tournaments t
            SET media_type = sub.media_type
            FROM (
                SELECT DISTINCT ON (tm.tournament_id)
                       tm.tournament_id, m.media_type
                FROM tournament_matches tm
                JOIN movies m ON m.id = tm.movie_a_id
                ORDER BY tm.tournament_id, tm.round, tm.position
            ) AS sub
            WHERE sub.tournament_id = t.id
            """
        )
    )


def downgrade() -> None:
    op.drop_column("tournaments", "media_type")
