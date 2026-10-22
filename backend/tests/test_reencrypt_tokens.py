"""Tests for the TOKEN_ENC_KEY rotation command (backend/scripts/reencrypt_tokens.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa

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


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, "
                "trakt_access_token TEXT, trakt_refresh_token TEXT, "
                "simkl_access_token TEXT, simkl_refresh_token TEXT)"
            )
        )
        connection.execute(
            sa.text(
                "CREATE TABLE feedback_reports "
                "(id INTEGER PRIMARY KEY, screenshot_data_enc TEXT)"
            )
        )
        yield connection


def _oauth(value: str) -> str:
    return encrypt_token(value, purpose=TokenPurpose.OAUTH)


def _rows(conn) -> list:
    return conn.execute(sa.text("SELECT * FROM users ORDER BY id")).fetchall()


def test_rewrites_previous_key_values_and_is_idempotent(conn, use_keys):
    use_keys(KEY_A)
    conn.execute(
        sa.text("INSERT INTO users VALUES (1, :ta, :tr, NULL, ''), (2, NULL, NULL, :sa, :sr)"),
        {"ta": _oauth("ta"), "tr": _oauth("tr"), "sa": _oauth("sa"), "sr": _oauth("sr")},
    )
    conn.execute(
        sa.text("INSERT INTO feedback_reports VALUES (1, :s), (2, NULL)"),
        {"s": encrypt_token("shot", purpose=TokenPurpose.SCREENSHOT)},
    )
    use_keys(KEY_B, previous=KEY_A)
    conn.execute(sa.text("INSERT INTO users VALUES (3, :ta, NULL, NULL, NULL)"), {"ta": _oauth("new")})
    already_current = _rows(conn)[2]

    assert reencrypt(conn) == (5, 0)
    after_first = _rows(conn)
    assert after_first[2] == already_current
    assert reencrypt(conn) == (0, 0)
    assert _rows(conn) == after_first

    use_keys(KEY_B)
    oauth = [
        decrypt_and_rotate(v, purpose=TokenPurpose.OAUTH)
        for row in after_first
        for v in row[1:]
    ]
    assert [plain for plain, _ in oauth] == ["ta", "tr", "", "", "", "", "sa", "sr", "new", "", "", ""]
    assert all(rotated is None for _, rotated in oauth)
    shot = conn.execute(sa.text("SELECT screenshot_data_enc FROM feedback_reports WHERE id = 1")).scalar_one()
    assert decrypt_and_rotate(shot, purpose=TokenPurpose.SCREENSHOT) == ("shot", None)


def test_unreadable_values_are_left_as_stored(conn, use_keys, caplog):
    use_keys(KEY_C)
    stale = _oauth("lost")
    use_keys(KEY_A)
    conn.execute(
        sa.text("INSERT INTO users VALUES (1, :stale, :ok, NULL, NULL)"),
        {"stale": stale, "ok": _oauth("ok")},
    )
    use_keys(KEY_B, previous=KEY_A)

    with caplog.at_level("WARNING", logger="reencrypt_tokens"):
        assert reencrypt(conn) == (1, 1)
    assert _rows(conn)[0].trakt_access_token == stale
    assert "users.trakt_access_token id=1" in caplog.text
    assert stale not in caplog.text
    with pytest.raises(TokenDecryptError):
        decrypt_and_rotate(stale, purpose=TokenPurpose.OAUTH)
