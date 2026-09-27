"""Keep a minimal duel history past the retention purge

Adds duels.outcome, the duel_history table the purge moves old duels into,
and lets that purge delete duels referenced by tournament matches.

Revision ID: 023
Revises: 022
Create Date: 2026-09-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision: str = "023"
down_revision: Union[str, None] = "022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Postgres's default name for the inline FK created in migration 005.
_TOURNAMENT_DUEL_FK = "tournament_matches_duel_id_fkey"


def upgrade() -> None:
    op.add_column("duels", sa.Column("outcome", sa.Text(), nullable=True))

    op.create_table(
        "duel_history",
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
            nullable=False,
        ),
        sa.Column(
            "winner_movie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("movies.id"),
            nullable=True,
        ),
        sa.Column(
            "loser_movie_id",
            UUID(as_uuid=True),
            sa.ForeignKey("movies.id"),
            nullable=True,
        ),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_duel_history_user_id", "duel_history", ["user_id"])

    op.drop_constraint(_TOURNAMENT_DUEL_FK, "tournament_matches", type_="foreignkey")
    op.create_foreign_key(
        _TOURNAMENT_DUEL_FK,
        "tournament_matches",
        "duels",
        ["duel_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_TOURNAMENT_DUEL_FK, "tournament_matches", type_="foreignkey")
    op.create_foreign_key(
        _TOURNAMENT_DUEL_FK, "tournament_matches", "duels", ["duel_id"], ["id"]
    )
    op.drop_index("ix_duel_history_user_id", table_name="duel_history")
    op.drop_table("duel_history")
    op.drop_column("duels", "outcome")
