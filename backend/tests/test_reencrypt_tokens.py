"""Tests for the TOKEN_ENC_KEY rotation command (backend/scripts/reencrypt_tokens.py)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa

from backend.db_models import FeedbackReport, User
from backend.scripts import reencrypt_tokens
from backend.scripts.reencrypt_tokens import reencrypt
from backend.services.token_crypto import (
    TokenDecryptError,
    TokenPurpose,
    _fernet,
    decrypt_and_rotate,
    encrypt_token,
)

KEY_A = "key-a-long-enough-for-validation-32chars"
KEY_B = "key-b-long-enough-for-validation-32chars"
KEY_C = "key-c-long-enough-for-validation-32chars"


@pytest.fixture
def use_keys():
    with patch("backend.services.token_crypto.get_settings") as get_settings:

        def _use(current: str, previous: str = "") -> None:
            _fernet.cache_clear()
            get_settings.return_value = MagicMock(
                TOKEN_ENC_KEY=current, TOKEN_ENC_KEY_PREVIOUS=previous
            )

        yield _use
    _fernet.cache_clear()


USERS = User.__table__
REPORTS = FeedbackReport.__table__
TOKEN_COLUMNS = (
    "trakt_access_token",
    "trakt_refresh_token",
    "simkl_access_token",
    "simkl_refresh_token",
)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        USERS.create(connection)
        REPORTS.create(connection)
        yield connection


def _oauth(value: str) -> str:
    return encrypt_token(value, purpose=TokenPurpose.OAUTH)


def _add_user(conn, **tokens) -> None:
    # created_at orders the rows _tokens returns.
    added = conn.execute(sa.select(sa.func.count()).select_from(USERS)).scalar_one()
    created_at = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=added)
    conn.execute(USERS.insert().values(created_at=created_at, **tokens))


def _tokens(conn) -> list[tuple]:
    columns = [USERS.c[name] for name in TOKEN_COLUMNS]
    return conn.execute(sa.select(*columns).order_by(USERS.c.created_at)).fetchall()


def _add_report(conn, screenshot) -> None:
    user_id = conn.execute(sa.select(USERS.c.id)).scalars().first()
    conn.execute(
        REPORTS.insert().values(
            user_id=user_id, title="t", description="d", screenshot_data_enc=screenshot
        )
    )


def test_rewrites_previous_key_values_and_is_idempotent(conn, use_keys):
    use_keys(KEY_A)
    _add_user(conn, trakt_access_token=_oauth("ta"), trakt_refresh_token=_oauth("tr"), simkl_refresh_token="")
    _add_user(conn, simkl_access_token=_oauth("sa"), simkl_refresh_token=_oauth("sr"))
    _add_report(conn, encrypt_token("shot", purpose=TokenPurpose.SCREENSHOT))
    _add_report(conn, None)
    use_keys(KEY_B, previous=KEY_A)
    _add_user(conn, trakt_access_token=_oauth("new"))
    already_current = _tokens(conn)[2]

    assert reencrypt(conn) == (5, 0)
    after_first = _tokens(conn)
    assert after_first[2] == already_current
    assert reencrypt(conn) == (0, 0)
    assert _tokens(conn) == after_first

    use_keys(KEY_B)
    oauth = [
        decrypt_and_rotate(v, purpose=TokenPurpose.OAUTH)
        for row in after_first
        for v in row
    ]
    assert [plain for plain, _ in oauth] == ["ta", "tr", "", "", "", "", "sa", "sr", "new", "", "", ""]
    assert all(rotated is None for _, rotated in oauth)
    shots = conn.execute(
        sa.select(REPORTS.c.screenshot_data_enc).where(REPORTS.c.screenshot_data_enc.is_not(None))
    ).scalars().all()
    assert [decrypt_and_rotate(s, purpose=TokenPurpose.SCREENSHOT) for s in shots] == [("shot", None)]


def test_covers_every_encrypted_token_column():
    assert [column.name for column, purpose in reencrypt_tokens._COLUMNS
            if purpose is TokenPurpose.OAUTH] == list(TOKEN_COLUMNS)


def test_unreadable_values_are_left_as_stored(conn, use_keys, caplog):
    use_keys(KEY_C)
    stale = _oauth("lost")
    use_keys(KEY_A)
    _add_user(conn, trakt_access_token=stale, trakt_refresh_token=_oauth("ok"))
    use_keys(KEY_B, previous=KEY_A)

    with caplog.at_level("WARNING", logger="reencrypt_tokens"):
        assert reencrypt(conn) == (1, 1)
    assert _tokens(conn)[0].trakt_access_token == stale
    assert "users.trakt_access_token id=" in caplog.text
    assert stale not in caplog.text
    with pytest.raises(TokenDecryptError):
        decrypt_and_rotate(stale, purpose=TokenPurpose.OAUTH)


def _between_read_and_write(monkeypatch, action) -> None:
    """Run ``action(value)`` after the script reads a value, before it writes one back."""
    real = reencrypt_tokens.decrypt_and_rotate

    def racing(value, *, purpose):
        result = real(value, purpose=purpose)
        action(value)
        return result

    monkeypatch.setattr(reencrypt_tokens, "decrypt_and_rotate", racing)


def test_value_stored_since_the_read_is_not_overwritten(conn, use_keys, monkeypatch):
    use_keys(KEY_A)
    _add_user(conn, trakt_access_token=_oauth("old"))
    use_keys(KEY_B, previous=KEY_A)
    newer = _oauth("newer")
    _between_read_and_write(
        monkeypatch, lambda _: conn.execute(USERS.update().values(trakt_access_token=newer))
    )

    assert reencrypt(conn) == (0, 0)
    assert _tokens(conn)[0].trakt_access_token == newer


def test_row_deleted_mid_run_is_skipped(conn, use_keys, monkeypatch):
    use_keys(KEY_A)
    _add_user(conn, trakt_access_token=_oauth("one"))
    _add_user(conn, trakt_access_token=_oauth("two"))
    use_keys(KEY_B, previous=KEY_A)
    _between_read_and_write(
        monkeypatch,
        lambda value: conn.execute(USERS.delete().where(USERS.c.trakt_access_token != value)),
    )

    assert reencrypt(conn) == (1, 0)
    [(survivor, *_)] = _tokens(conn)
    use_keys(KEY_B)
    assert decrypt_and_rotate(survivor, purpose=TokenPurpose.OAUTH)[1] is None
