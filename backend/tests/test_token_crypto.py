"""Tests for token encryption/decryption (backend/services/token_crypto.py)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from backend.db_models import User
from backend.services.token_crypto import (
    TokenDecryptError,
    TokenPurpose,
    _fernet,
    decrypt_and_rotate,
    decrypt_token,
    encrypt_token,
)

OAUTH = TokenPurpose.OAUTH


@pytest.fixture(autouse=True)
def _clear_fernet_cache():
    """Clear the cached Fernet instance before each test."""
    _fernet.cache_clear()
    yield
    _fernet.cache_clear()


KEY_A = "key-a-long-enough-for-validation-32chars"
KEY_B = "key-b-long-enough-for-validation-32chars"
KEY_C = "key-c-long-enough-for-validation-32chars"


def _mock_settings(
    token_enc_key: str = "a-very-long-test-key-that-is-at-least-32-characters",
    previous: str = "",
):
    settings = MagicMock()
    settings.TOKEN_ENC_KEY = token_enc_key
    settings.TOKEN_ENC_KEY_PREVIOUS = previous
    return settings


def _rotate_to(mock_get_settings, current: str, previous: str = "") -> None:
    _fernet.cache_clear()
    mock_get_settings.return_value = _mock_settings(current, previous)


class TestTokenCrypto:
    @patch("backend.services.token_crypto.get_settings")
    def test_roundtrip(self, mock_get_settings):
        """decrypt_token(encrypt_token(secret)) should return the original secret."""
        mock_get_settings.return_value = _mock_settings()
        plaintext = "my-secret-oauth-token"
        ciphertext = encrypt_token(plaintext, purpose=OAUTH)
        assert ciphertext != plaintext
        assert decrypt_token(ciphertext, purpose=OAUTH) == plaintext

    @patch("backend.services.token_crypto.get_settings")
    def test_wrong_key_raises(self, mock_get_settings):
        """Decrypting with a different key should raise RuntimeError."""
        mock_get_settings.return_value = _mock_settings("key-a-long-enough-for-validation-32chars")
        ciphertext = encrypt_token("secret", purpose=OAUTH)

        _fernet.cache_clear()
        mock_get_settings.return_value = _mock_settings("key-b-long-enough-for-validation-32chars")

        with pytest.raises(RuntimeError, match="Token decryption failed"):
            decrypt_token(ciphertext, purpose=OAUTH)

    @patch("backend.services.token_crypto.get_settings")
    def test_empty_string_noop(self, mock_get_settings):
        """Empty strings should pass through without encryption."""
        mock_get_settings.return_value = _mock_settings()
        assert encrypt_token("", purpose=OAUTH) == ""
        assert decrypt_token("", purpose=OAUTH) == ""

    @patch("backend.services.token_crypto.get_settings")
    def test_missing_key_raises(self, mock_get_settings):
        """An empty TOKEN_ENC_KEY should raise RuntimeError."""
        mock_get_settings.return_value = _mock_settings("")
        with pytest.raises(RuntimeError, match="TOKEN_ENC_KEY is not set"):
            encrypt_token("x", purpose=OAUTH)

    @patch("backend.services.token_crypto.get_settings")
    def test_fernet_cached(self, mock_get_settings):
        """_fernet() should return the same instance on repeated calls (lru_cache)."""
        mock_get_settings.return_value = _mock_settings()
        first = _fernet(OAUTH)
        second = _fernet(OAUTH)
        assert first is second

    @patch("backend.services.token_crypto.get_settings")
    def test_key_derivation_is_deterministic(self, mock_get_settings):
        """Same TOKEN_ENC_KEY always produces the same Fernet key (HKDF is deterministic)."""
        mock_get_settings.return_value = _mock_settings()
        ciphertext = encrypt_token("determinism-check", purpose=OAUTH)

        # Clear cache and re-derive — must still decrypt successfully
        _fernet.cache_clear()
        assert decrypt_token(ciphertext, purpose=OAUTH) == "determinism-check"

    @patch("backend.services.token_crypto.get_settings")
    def test_ttl_rejects_expired(self, mock_get_settings):
        """A ttl rejects tokens older than it; the default (no ttl) never expires."""
        mock_get_settings.return_value = _mock_settings()
        ciphertext = _fernet(OAUTH).encrypt_at_time(b"secret", int(time.time()) - 120).decode()

        with pytest.raises(RuntimeError, match="Token decryption failed"):
            decrypt_token(ciphertext, purpose=OAUTH, ttl=60)
        assert decrypt_token(ciphertext, purpose=OAUTH) == "secret"

    @patch("backend.services.token_crypto.get_settings")
    def test_purposes_do_not_decrypt_each_other(self, mock_get_settings):
        """Ciphertext minted for one purpose is rejected under every other one."""
        mock_get_settings.return_value = _mock_settings()
        for minted in TokenPurpose:
            ciphertext = encrypt_token("secret", purpose=minted)
            for other in TokenPurpose:
                if other is minted:
                    assert decrypt_token(ciphertext, purpose=other) == "secret"
                else:
                    with pytest.raises(RuntimeError, match="Token decryption failed"):
                        decrypt_token(ciphertext, purpose=other)


@patch("backend.services.token_crypto.get_settings")
class TestKeyRotation:
    def test_previous_key_decrypts_and_rotates_to_current(self, mock_get_settings):
        _rotate_to(mock_get_settings, KEY_A)
        ciphertext = encrypt_token("secret", purpose=OAUTH)

        _rotate_to(mock_get_settings, KEY_B, previous=f" {KEY_C} , {KEY_A} ")
        assert decrypt_token(ciphertext, purpose=OAUTH) == "secret"
        plain, rotated = decrypt_and_rotate(ciphertext, purpose=OAUTH)
        assert plain == "secret"

        _rotate_to(mock_get_settings, KEY_B)
        assert decrypt_and_rotate(rotated, purpose=OAUTH) == ("secret", None)

    def test_current_key_value_is_not_rotated(self, mock_get_settings):
        _rotate_to(mock_get_settings, KEY_B, previous=KEY_A)
        ciphertext = encrypt_token("secret", purpose=OAUTH)
        assert decrypt_and_rotate(ciphertext, purpose=OAUTH) == ("secret", None)
        assert decrypt_and_rotate("", purpose=OAUTH) == ("", None)

    def test_previous_key_never_encrypts(self, mock_get_settings):
        _rotate_to(mock_get_settings, KEY_B, previous=KEY_A)
        ciphertext = encrypt_token("secret", purpose=OAUTH)
        _rotate_to(mock_get_settings, KEY_A)
        with pytest.raises(TokenDecryptError):
            decrypt_token(ciphertext, purpose=OAUTH)

    def test_unknown_key_raises(self, mock_get_settings):
        _rotate_to(mock_get_settings, KEY_A)
        ciphertext = encrypt_token("secret", purpose=OAUTH)
        _rotate_to(mock_get_settings, KEY_B, previous=KEY_C)
        with pytest.raises(TokenDecryptError, match="Token decryption failed"):
            decrypt_and_rotate(ciphertext, purpose=OAUTH)


@patch("backend.services.token_crypto.get_settings")
class TestEncryptedTokenRotation:
    def test_row_under_previous_key_is_rewritten_under_current(self, mock_get_settings):
        _rotate_to(mock_get_settings, KEY_A)
        user = User(trakt_access_token="oauth-access")
        stored_under_a = user.trakt_access_token_enc

        _rotate_to(mock_get_settings, KEY_B, previous=KEY_A)
        assert user.trakt_access_token == "oauth-access"
        assert user.trakt_access_token_enc != stored_under_a

        _rotate_to(mock_get_settings, KEY_B)
        assert user.trakt_access_token == "oauth-access"

    def test_row_no_key_decrypts_reads_as_disconnected(self, mock_get_settings, caplog):
        _rotate_to(mock_get_settings, KEY_A)
        user = User(trakt_access_token="oauth-access")
        stored_under_a = user.trakt_access_token_enc

        _rotate_to(mock_get_settings, KEY_B)
        with caplog.at_level("WARNING", logger="backend.db_models"):
            assert user.trakt_access_token == ""
        assert user.trakt_access_token_enc == stored_under_a
        assert "oauth_token_undecryptable" in caplog.text
        assert stored_under_a not in caplog.text
