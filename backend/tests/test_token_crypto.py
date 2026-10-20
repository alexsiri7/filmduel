"""Tests for token encryption/decryption (backend/services/token_crypto.py)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from backend.services.token_crypto import (
    TokenPurpose,
    _fernet,
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


def _mock_settings(token_enc_key: str = "a-very-long-test-key-that-is-at-least-32-characters"):
    settings = MagicMock()
    settings.TOKEN_ENC_KEY = token_enc_key
    return settings


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
