"""Re-encrypt stored OAuth tokens and screenshots under per-purpose HKDF keys.

Until now every encrypted value shared one HKDF context (fernet-key-v2).
OAuth tokens and feedback screenshots now each derive their own key; pair
tokens are never stored, so the ones in flight at deploy simply stop
decrypting and clients fetch a fresh pair.

A stored value neither key decrypts is already unusable, so it is set to
NULL with a warning naming the row (the user is asked to reconnect). If no
value decrypts at all, TOKEN_ENC_KEY is wrong and the migration aborts
without writing anything.

Revision ID: 028
Revises: 027
Create Date: 2026-10-20
"""

from __future__ import annotations

import base64
import logging
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

logger = logging.getLogger("alembic.runtime.migration")

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


# Outcome of re-keying one value.
_EMPTY = "empty"  # None or "", passed through
_SOURCE = "source"  # decrypted with the source key and re-encrypted
_DEST = "dest"  # already under the destination key (a re-run)
_UNREADABLE = "unreadable"  # neither key decrypts it: stored as NULL


def _rekey(value: str | None, source: Fernet, dest: Fernet) -> tuple[str | None, str]:
    """Decrypt with source, re-encrypt with dest; return (new value, outcome).

    A value dest already decrypts is returned unchanged, so a re-run after a
    partial failure is safe. A value neither key decrypts comes back as None:
    it is unusable either way, and the app treats a NULL token as "not
    connected" and asks the user to reconnect.
    """
    if not value:
        return value, _EMPTY
    try:
        plaintext = source.decrypt(value.encode())
    except InvalidToken:
        try:
            dest.decrypt(value.encode())
        except InvalidToken:
            return None, _UNREADABLE
        return value, _DEST
    return dest.encrypt(plaintext).decode(), _SOURCE


class _Tally:
    """Counts outcomes across every table so one guard covers the whole run."""

    def __init__(self) -> None:
        self.readable = 0
        self.unreadable: list[tuple[str, str, object]] = []

    def add(self, outcome: str, table: str, column: str, row_id: object) -> None:
        if outcome in (_SOURCE, _DEST):
            self.readable += 1
        elif outcome == _UNREADABLE:
            self.unreadable.append((table, column, row_id))

    def check(self) -> None:
        """Abort when nothing decrypts but something fails: the key is wrong.

        Nulling then would wipe every stored token and screenshot, so a
        misconfigured TOKEN_ENC_KEY must stop the migration instead.
        """
        if self.unreadable and not self.readable:
            raise RuntimeError(
                f"Re-key aborted: none of the {len(self.unreadable)} stored encrypted "
                "values decrypts with the source or destination key. "
                "TOKEN_ENC_KEY is probably wrong; refusing to clear them."
            )

    def warn(self) -> None:
        for table, column, row_id in self.unreadable:
            logger.warning(
                "Re-key: %s.%s for id=%s cannot be decrypted with either key; "
                "setting it to NULL",
                table,
                column,
                row_id,
            )


def _plan_users(conn, source: Fernet, dest: Fernet, tally: _Tally) -> list[dict]:
    columns = ", ".join(_USER_TOKEN_COLUMNS)
    rows = conn.execute(sa.text(f"SELECT id, {columns} FROM users")).fetchall()
    updates = []
    for row in rows:
        params: dict = {"id": row.id}
        for c in _USER_TOKEN_COLUMNS:
            params[c], outcome = _rekey(getattr(row, c), source, dest)
            tally.add(outcome, "users", c, row.id)
        updates.append(params)
    return updates


def _write_users(conn, updates: list[dict]) -> None:
    assignments = ", ".join(f"{c} = :{c}" for c in _USER_TOKEN_COLUMNS)
    for params in updates:
        conn.execute(
            sa.text(f"UPDATE users SET {assignments} WHERE id = :id"), params
        )


def _screenshot_ids(conn) -> list:
    return conn.execute(
        sa.text(
            "SELECT id FROM feedback_reports WHERE screenshot_data_enc IS NOT NULL"
        )
    ).scalars().all()


def _screenshot(conn, report_id) -> str | None:
    return conn.execute(
        sa.text("SELECT screenshot_data_enc FROM feedback_reports WHERE id = :id"),
        {"id": report_id},
    ).scalar_one()


def _plan_screenshots(conn, source: Fernet, dest: Fernet, tally: _Tally) -> list:
    # Screenshots run to megabytes each, so load one at a time and keep only
    # the outcome; _write_screenshots re-reads each one.
    ids = _screenshot_ids(conn)
    for report_id in ids:
        _, outcome = _rekey(_screenshot(conn, report_id), source, dest)
        tally.add(outcome, "feedback_reports", "screenshot_data_enc", report_id)
    return ids


def _write_screenshots(conn, ids: list, source: Fernet, dest: Fernet) -> None:
    for report_id in ids:
        rekeyed, _ = _rekey(_screenshot(conn, report_id), source, dest)
        conn.execute(
            sa.text(
                "UPDATE feedback_reports SET screenshot_data_enc = :v WHERE id = :id"
            ),
            {"id": report_id, "v": rekeyed},
        )


def _run(conn, user_keys: tuple[Fernet, Fernet], shot_keys: tuple[Fernet, Fernet]) -> None:
    """Plan every change, check the key guard, then write.

    Nothing is written before the guard passes, so a wrong key leaves the
    database untouched.
    """
    tally = _Tally()
    user_updates = _plan_users(conn, *user_keys, tally)
    shot_ids = _plan_screenshots(conn, *shot_keys, tally)
    tally.check()
    tally.warn()
    _write_users(conn, user_updates)
    _write_screenshots(conn, shot_ids, *shot_keys)


def _fernets_from_settings() -> tuple[Fernet, Fernet, Fernet]:
    from backend.config import get_settings

    settings = get_settings()
    if not settings.TOKEN_ENC_KEY:
        raise RuntimeError("TOKEN_ENC_KEY must be set to run this migration")
    return _make_fernets(settings.TOKEN_ENC_KEY)


def upgrade() -> None:
    shared, oauth, screenshot = _fernets_from_settings()
    _run(op.get_bind(), (shared, oauth), (shared, screenshot))


def downgrade() -> None:
    """Revert to the single shared key.

    IMPORTANT: Roll back the application code (token_crypto.py) to the
    shared-key version BEFORE running this downgrade, otherwise live instances
    will fail to decrypt reverted values.
    """
    shared, oauth, screenshot = _fernets_from_settings()
    _run(op.get_bind(), (oauth, shared), (screenshot, shared))
