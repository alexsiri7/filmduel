"""Add trakt_uuid to users as the stable Trakt account key.

Revision ID: 027
Revises: 026
Create Date: 2026-10-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("trakt_uuid", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_users_trakt_uuid", "users", ["trakt_uuid"])


def downgrade() -> None:
    op.drop_constraint("uq_users_trakt_uuid", "users", type_="unique")
    op.drop_column("users", "trakt_uuid")
