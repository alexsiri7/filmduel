"""Store ELO ratings as floats

Ratings stop being rounded to an integer on every update (#649): under
K = 300/sqrt(battles+1) a mature film's update is often under one point.

Revision ID: 024
Revises: 023
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "024"
down_revision: Union[str, None] = "023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ELO_COLUMNS = [
    ("user_movies", "elo"),
    ("duels", "winner_elo_before"),
    ("duels", "loser_elo_before"),
    ("duels", "winner_elo_after"),
    ("duels", "loser_elo_after"),
]


def upgrade() -> None:
    for table, column in _ELO_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Float(),
            existing_type=sa.Integer(),
            existing_nullable=True,
        )


def downgrade() -> None:
    for table, column in _ELO_COLUMNS:
        op.alter_column(
            table,
            column,
            type_=sa.Integer(),
            existing_type=sa.Float(),
            existing_nullable=True,
            postgresql_using=f"round({column})::integer",
        )
