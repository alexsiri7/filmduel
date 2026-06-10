"""Re-encrypt stored tokens using HKDF instead of SHA-256 key derivation.

Revision ID: 020
Revises: 019
Create Date: 2026-06-10
"""

from __future__ import annotations

import base64
import hashlib
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _make_fernets(token_enc_key: str) -> tuple[Fernet, Fernet]:
    """Return (old_fernet using sha256, new_fernet using hkdf)."""
    raw = token_enc_key.encode()

    # Old derivation: SHA-256 direct hash
    old_key = base64.urlsafe_b64encode(hashlib.sha256(raw).digest())

    # New derivation: HKDF
    new_key = base64.urlsafe_b64encode(
        HKDF(
            algorithm=SHA256(),
            length=32,
            salt=b"filmduel-token-enc",
            info=b"fernet-key-v2",
        ).derive(raw)
    )

    return Fernet(old_key), Fernet(new_key)


def _rekey(value: str | None, old: Fernet, new: Fernet) -> str | None:
    """Decrypt with old key, re-encrypt with new key. Returns None if value is None/empty."""
    if not value:
        return value
    try:
        plaintext = old.decrypt(value.encode())
    except InvalidToken:
        # Already re-keyed (e.g., migration run twice) — try new key, leave as-is
        try:
            new.decrypt(value.encode())
            return value  # already re-keyed
        except InvalidToken:
            raise RuntimeError(
                "Token cannot be decrypted with either old or new key. "
                "Check TOKEN_ENC_KEY matches the key used during encryption."
            )
    return new.encrypt(plaintext).decode()


def upgrade() -> None:
    from backend.config import get_settings

    settings = get_settings()
    if not settings.TOKEN_ENC_KEY:
        raise RuntimeError("TOKEN_ENC_KEY must be set to run this migration")

    old_fernet, new_fernet = _make_fernets(settings.TOKEN_ENC_KEY)
    conn = op.get_bind()

    # Re-key user OAuth tokens (trakt + simkl)
    rows = conn.execute(
        sa.text(
            "SELECT id, trakt_access_token, trakt_refresh_token, "
            "simkl_access_token, simkl_refresh_token FROM users"
        )
    ).fetchall()

    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE users SET "
                "trakt_access_token = :ta, trakt_refresh_token = :tr, "
                "simkl_access_token = :sa, simkl_refresh_token = :sr "
                "WHERE id = :id"
            ),
            {
                "id": row.id,
                "ta": _rekey(row.trakt_access_token, old_fernet, new_fernet),
                "tr": _rekey(row.trakt_refresh_token, old_fernet, new_fernet),
                "sa": _rekey(row.simkl_access_token, old_fernet, new_fernet),
                "sr": _rekey(row.simkl_refresh_token, old_fernet, new_fernet),
            },
        )

    # Note: feedback screenshot_data_enc was NULLed in migration 015 (no re-keying needed)
    # Note: movie pair tokens are ephemeral and regenerated on next request


def downgrade() -> None:
    from backend.config import get_settings

    settings = get_settings()
    if not settings.TOKEN_ENC_KEY:
        raise RuntimeError("TOKEN_ENC_KEY must be set to run this migration")

    old_fernet, new_fernet = _make_fernets(settings.TOKEN_ENC_KEY)
    conn = op.get_bind()

    rows = conn.execute(
        sa.text(
            "SELECT id, trakt_access_token, trakt_refresh_token, "
            "simkl_access_token, simkl_refresh_token FROM users"
        )
    ).fetchall()

    for row in rows:
        conn.execute(
            sa.text(
                "UPDATE users SET "
                "trakt_access_token = :ta, trakt_refresh_token = :tr, "
                "simkl_access_token = :sa, simkl_refresh_token = :sr "
                "WHERE id = :id"
            ),
            {
                "id": row.id,
                "ta": _rekey(row.trakt_access_token, new_fernet, old_fernet),
                "tr": _rekey(row.trakt_refresh_token, new_fernet, old_fernet),
                "sa": _rekey(row.simkl_access_token, new_fernet, old_fernet),
                "sr": _rekey(row.simkl_refresh_token, new_fernet, old_fernet),
            },
        )
