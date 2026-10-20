"""Re-encrypt stored OAuth tokens and screenshots under per-purpose HKDF keys.

Until now every encrypted value shared one HKDF context (fernet-key-v2).
OAuth tokens and feedback screenshots now each derive their own key; pair
tokens are never stored, so the ones in flight at deploy simply stop
decrypting and clients fetch a fresh pair.

Revision ID: 028
Revises: 027
Create Date: 2026-10-20
"""

from __future__ import annotations

import base64
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

revision: str = "028"
down_revision: Union[str, None] = "027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen copies of the HKDF info strings: the migration must keep deriving
# these exact keys even if token_crypto.TokenPurpose changes later.
_SHARED_INFO = b"fernet-key-v2"
_OAUTH_INFO = b"fernet-key-v3/oauth-token"
_SCREENSHOT_INFO = b"fernet-key-v3/feedback-screenshot"

_USER_TOKEN_COLUMNS = (
    "trakt_access_token",
    "trakt_refresh_token",
    "simkl_access_token",
    "simkl_refresh_token",
)


def _derive(token_enc_key: str, info: bytes) -> Fernet:
    key = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=b"filmduel-token-enc",
        info=info,
    ).derive(token_enc_key.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def _make_fernets(token_enc_key: str) -> tuple[Fernet, Fernet, Fernet]:
    """Return (shared, oauth, screenshot) Fernets."""
    return (
        _derive(token_enc_key, _SHARED_INFO),
        _derive(token_enc_key, _OAUTH_INFO),
        _derive(token_enc_key, _SCREENSHOT_INFO),
    )


def _rekey(value: str | None, source: Fernet, dest: Fernet) -> str | None:
    """Decrypt with source, re-encrypt with dest. None and empty pass through.

    A value dest already decrypts is returned unchanged, so a re-run after a
    partial failure is safe.
    """
    if not value:
        return value
    try:
        plaintext = source.decrypt(value.encode())
    except InvalidToken:
        try:
            dest.decrypt(value.encode())
        except InvalidToken:
            raise RuntimeError(
                "Value cannot be decrypted with either the source or destination key. "
                "Check TOKEN_ENC_KEY matches the key used during encryption."
            ) from None
        return value
    return dest.encrypt(plaintext).decode()


def _rekey_users(conn, source: Fernet, dest: Fernet) -> None:
    columns = ", ".join(_USER_TOKEN_COLUMNS)
    assignments = ", ".join(f"{c} = :{c}" for c in _USER_TOKEN_COLUMNS)
    rows = conn.execute(sa.text(f"SELECT id, {columns} FROM users")).fetchall()
    for row in rows:
        try:
            params = {
                c: _rekey(getattr(row, c), source, dest) for c in _USER_TOKEN_COLUMNS
            }
        except RuntimeError as exc:
            raise RuntimeError(f"Re-key failed for user id={row.id}: {exc}") from exc
        conn.execute(
            sa.text(f"UPDATE users SET {assignments} WHERE id = :id"),
            {"id": row.id, **params},
        )


def _rekey_screenshots(conn, source: Fernet, dest: Fernet) -> None:
    # Screenshots run to megabytes each, so load one at a time.
    ids = conn.execute(
        sa.text(
            "SELECT id FROM feedback_reports WHERE screenshot_data_enc IS NOT NULL"
        )
    ).scalars().all()
    for report_id in ids:
        value = conn.execute(
            sa.text("SELECT screenshot_data_enc FROM feedback_reports WHERE id = :id"),
            {"id": report_id},
        ).scalar_one()
        try:
            rekeyed = _rekey(value, source, dest)
        except RuntimeError as exc:
            raise RuntimeError(
                f"Re-key failed for feedback report id={report_id}: {exc}"
            ) from exc
        conn.execute(
            sa.text(
                "UPDATE feedback_reports SET screenshot_data_enc = :v WHERE id = :id"
            ),
            {"id": report_id, "v": rekeyed},
        )


def _fernets_from_settings() -> tuple[Fernet, Fernet, Fernet]:
    from backend.config import get_settings

    settings = get_settings()
    if not settings.TOKEN_ENC_KEY:
        raise RuntimeError("TOKEN_ENC_KEY must be set to run this migration")
    return _make_fernets(settings.TOKEN_ENC_KEY)


def upgrade() -> None:
    shared, oauth, screenshot = _fernets_from_settings()
    conn = op.get_bind()
    _rekey_users(conn, shared, oauth)
    _rekey_screenshots(conn, shared, screenshot)


def downgrade() -> None:
    """Revert to the single shared key.

    IMPORTANT: Roll back the application code (token_crypto.py) to the
    shared-key version BEFORE running this downgrade, otherwise live instances
    will fail to decrypt reverted values.
    """
    shared, oauth, screenshot = _fernets_from_settings()
    conn = op.get_bind()
    _rekey_users(conn, oauth, shared)
    _rekey_screenshots(conn, screenshot, shared)
