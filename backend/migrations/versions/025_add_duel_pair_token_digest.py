"""Record which pair token each duel consumed

A retried submission whose first response was lost re-sends the same pair
token; the unique digest lets POST /api/duels reject the replay instead of
applying the duel twice.

Revision ID: 025
Revises: 024
Create Date: 2026-09-28
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("duels", sa.Column("pair_token_digest", sa.Text(), nullable=True))
    op.create_index(
        "uq_duels_pair_token_digest", "duels", ["pair_token_digest"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_duels_pair_token_digest", table_name="duels")
    op.drop_column("duels", "pair_token_digest")
