"""Checks for migration 028, which CI never runs through Alembic."""

from __future__ import annotations

import importlib.util
import pathlib
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from cryptography.fernet import Fernet

from backend.services.token_crypto import TokenPurpose, _fernet, decrypt_token

_migration_path = (
    pathlib.Path(__file__).parent.parent
    / "migrations"
    / "versions"
    / "028_rekey_tokens_per_purpose.py"
)


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _migration_path.with_name(name))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_migration = _load("028_rekey_tokens_per_purpose.py")

TEST_KEY = "a-very-long-test-key-that-is-at-least-32-characters"
SCREENSHOT = "data:image/png;base64,iVBORw0KGgo="


@pytest.fixture(autouse=True)
def _settings():
    settings = MagicMock(TOKEN_ENC_KEY=TEST_KEY)
    _fernet.cache_clear()
    with (
        patch("backend.services.token_crypto.get_settings", return_value=settings),
        patch("backend.config.get_settings", return_value=settings),
    ):
        yield
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
        with patch.object(_migration.op, "get_bind", return_value=connection, create=True):
            yield connection


def _seed(conn, shared):
    conn.execute(
        sa.text(
            "INSERT INTO users VALUES "
            "(1, :ta, :tr, NULL, ''), (2, NULL, NULL, :sa, :sr)"
        ),
        {
            "ta": shared.encrypt(b"trakt-access").decode(),
            "tr": shared.encrypt(b"trakt-refresh").decode(),
            "sa": shared.encrypt(b"simkl-access").decode(),
            "sr": shared.encrypt(b"simkl-refresh").decode(),
        },
    )
    conn.execute(
        sa.text("INSERT INTO feedback_reports VALUES (1, :s), (2, NULL)"),
        {"s": shared.encrypt(SCREENSHOT.encode()).decode()},
    )


def _users(conn):
    return conn.execute(sa.text("SELECT * FROM users ORDER BY id")).fetchall()


def _screenshot(conn):
    return conn.execute(
        sa.text("SELECT screenshot_data_enc FROM feedback_reports WHERE id = 1")
    ).scalar_one()


def test_revises_the_previous_head():
    assert _migration.revision == "028"
    assert _migration.down_revision == "027"


def test_upgrade_moves_stored_values_onto_the_app_purpose_keys(conn):
    shared, _, _ = _migration._make_fernets(TEST_KEY)
    _seed(conn, shared)

    _migration.upgrade()

    oauth = lambda v: decrypt_token(v, purpose=TokenPurpose.OAUTH)  # noqa: E731
    first, second = _users(conn)
    assert (oauth(first.trakt_access_token), oauth(first.trakt_refresh_token)) == (
        "trakt-access",
        "trakt-refresh",
    )
    assert (first.simkl_access_token, first.simkl_refresh_token) == (None, "")
    assert (oauth(second.simkl_access_token), oauth(second.simkl_refresh_token)) == (
        "simkl-access",
        "simkl-refresh",
    )
    assert decrypt_token(_screenshot(conn), purpose=TokenPurpose.SCREENSHOT) == SCREENSHOT


def test_upgrade_is_safe_to_rerun(conn):
    shared, _, _ = _migration._make_fernets(TEST_KEY)
    _seed(conn, shared)
    _migration.upgrade()
    after_first = (_users(conn), _screenshot(conn))

    _migration.upgrade()

    assert (_users(conn), _screenshot(conn)) == after_first


def test_downgrade_restores_the_shared_key(conn):
    shared, _, _ = _migration._make_fernets(TEST_KEY)
    _seed(conn, shared)
    _migration.upgrade()

    _migration.downgrade()

    assert shared.decrypt(_users(conn)[0].trakt_access_token.encode()) == b"trakt-access"
    assert shared.decrypt(_screenshot(conn).encode()) == SCREENSHOT.encode()


def test_undecryptable_values_are_nulled_and_good_ones_rekeyed(conn, caplog):
    shared, _, _ = _migration._make_fernets(TEST_KEY)
    _seed(conn, shared)
    stale = Fernet(Fernet.generate_key())
    conn.execute(
        sa.text("INSERT INTO users VALUES (3, :ta, :tr, NULL, NULL)"),
        {
            "ta": stale.encrypt(b"old-access").decode(),
            "tr": stale.encrypt(b"old-refresh").decode(),
        },
    )
    conn.execute(
        sa.text("INSERT INTO feedback_reports VALUES (7, :s)"),
        {"s": stale.encrypt(SCREENSHOT.encode()).decode()},
    )

    with caplog.at_level("WARNING"):
        _migration.upgrade()

    oauth = lambda v: decrypt_token(v, purpose=TokenPurpose.OAUTH)  # noqa: E731
    first, second, third = _users(conn)
    assert oauth(first.trakt_access_token) == "trakt-access"
    assert oauth(second.simkl_refresh_token) == "simkl-refresh"
    assert (third.trakt_access_token, third.trakt_refresh_token) == (None, None)
    assert decrypt_token(_screenshot(conn), purpose=TokenPurpose.SCREENSHOT) == SCREENSHOT
    assert (
        conn.execute(
            sa.text("SELECT screenshot_data_enc FROM feedback_reports WHERE id = 7")
        ).scalar_one()
        is None
    )
    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("users.trakt_access_token for id=3" in m for m in warnings)
    assert any("users.trakt_refresh_token for id=3" in m for m in warnings)
    assert any("feedback_reports.screenshot_data_enc for id=7" in m for m in warnings)
    # The values themselves never reach the log.
    assert not any("gAAAA" in m for m in warnings)


def test_nulled_rows_survive_a_rerun(conn):
    shared, _, _ = _migration._make_fernets(TEST_KEY)
    _seed(conn, shared)
    conn.execute(sa.text("INSERT INTO users VALUES (3, 'garbage', NULL, NULL, NULL)"))
    _migration.upgrade()
    after_first = (_users(conn), _screenshot(conn))

    _migration.upgrade()

    assert (_users(conn), _screenshot(conn)) == after_first


def test_wrong_key_aborts_without_touching_anything(conn):
    """When nothing decrypts, TOKEN_ENC_KEY is wrong: never wipe every token."""
    other_key = Fernet(Fernet.generate_key())
    _seed(conn, other_key)
    before = (_users(conn), _screenshot(conn))

    with pytest.raises(RuntimeError, match="TOKEN_ENC_KEY is probably wrong"):
        _migration.upgrade()

    assert (_users(conn), _screenshot(conn)) == before


def test_empty_tables_need_no_key_check(conn):
    _migration.upgrade()
    assert _users(conn) == []


def test_plaintext_tokens_survive_the_whole_encryption_chain(conn):
    """013 encrypts, 020 re-keys, 028 moves onto the OAuth key, in one upgrade."""
    conn.execute(
        sa.text("INSERT INTO users VALUES (1, 'trakt-access', 'trakt-refresh', NULL, NULL)")
    )

    for name in (
        "013_encrypt_trakt_tokens.py",
        "020_rekey_tokens_hkdf.py",
        "028_rekey_tokens_per_purpose.py",
    ):
        _load(name).upgrade()

    user = _users(conn)[0]
    assert decrypt_token(user.trakt_access_token, purpose=TokenPurpose.OAUTH) == "trakt-access"
    assert decrypt_token(user.trakt_refresh_token, purpose=TokenPurpose.OAUTH) == "trakt-refresh"
