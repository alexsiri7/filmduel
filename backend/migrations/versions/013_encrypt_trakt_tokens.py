"""Encrypt existing Trakt OAuth tokens at rest.

Revision ID: 013
Revises: 012
Create Date: 2026-05-05
"""

from __future__ import annotations

import base64
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copy of the shared HKDF key: migrations 020 and 028 expect the
# ciphertext this writes, whatever token_crypto derives today.
_SHARED_INFO = b"fernet-key-v2"


def _make_fernet(token_enc_key: str) -> Fernet:
    key = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=b"filmduel-token-enc",
        info=_SHARED_INFO,
    ).derive(token_enc_key.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def _shared_fernet() -> Fernet:
    from backend.config import get_settings

    settings = get_settings()
    if not settings.TOKEN_ENC_KEY:
        raise RuntimeError("TOKEN_ENC_KEY must be set to run this migration")
    return _make_fernet(settings.TOKEN_ENC_KEY)


def _encrypt(fernet: Fernet, plain: str | None) -> str:
    return fernet.encrypt(plain.encode()).decode() if plain else ""


def _decrypt(fernet: Fernet, ciphertext: str | None) -> str:
    return fernet.decrypt(ciphertext.encode()).decode() if ciphertext else ""


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, trakt_access_token, trakt_refresh_token FROM users")
    ).fetchall()
    if not rows:
        return
    fernet = _shared_fernet()

    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE users SET "
                "trakt_access_token = :a, trakt_refresh_token = :r "
                "WHERE id = :id"
            ),
            {
                "id": row.id,
                "a": _encrypt(fernet, row.trakt_access_token),
                "r": _encrypt(fernet, row.trakt_refresh_token),
            },
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, trakt_access_token, trakt_refresh_token FROM users")
    ).fetchall()
    if not rows:
        return
    fernet = _shared_fernet()

    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE users SET "
                "trakt_access_token = :a, trakt_refresh_token = :r "
                "WHERE id = :id"
            ),
            {
                "id": row.id,
                "a": _decrypt(fernet, row.trakt_access_token),
                "r": _decrypt(fernet, row.trakt_refresh_token),
            },
        )
