"""Encrypt existing Trakt OAuth tokens at rest.

Revision ID: 013
Revises: 012
Create Date: 2026-05-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, trakt_access_token, trakt_refresh_token FROM users")
    ).fetchall()
    if not rows:
        return
    from backend.services.token_crypto import encrypt_token

    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE users SET "
                "trakt_access_token = :a, trakt_refresh_token = :r "
                "WHERE id = :id"
            ),
            {
                "id": row.id,
                "a": encrypt_token(row.trakt_access_token),
                "r": encrypt_token(row.trakt_refresh_token),
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, trakt_access_token, trakt_refresh_token FROM users")
    ).fetchall()
    from backend.services.token_crypto import decrypt_token

    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE users SET "
                "trakt_access_token = :a, trakt_refresh_token = :r "
                "WHERE id = :id"
            ),
            {
                "id": row.id,
                "a": decrypt_token(row.trakt_access_token),
                "r": decrypt_token(row.trakt_refresh_token),
            },
        )
