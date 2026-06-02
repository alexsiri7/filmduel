"""Tests for token encryption/decryption (backend/services/token_crypto.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.services.token_crypto import _fernet, decrypt_token, encrypt_token


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
        ciphertext = encrypt_token(plaintext)
        assert ciphertext != plaintext
        assert decrypt_token(ciphertext) == plaintext

    @patch("backend.services.token_crypto.get_settings")
    def test_wrong_key_raises(self, mock_get_settings):
        """Decrypting with a different key should raise RuntimeError."""
        mock_get_settings.return_value = _mock_settings("key-a-long-enough-for-validation-32chars")
        ciphertext = encrypt_token("secret")

        _fernet.cache_clear()
        mock_get_settings.return_value = _mock_settings("key-b-long-enough-for-validation-32chars")

        with pytest.raises(RuntimeError, match="Token decryption failed"):
            decrypt_token(ciphertext)

    @patch("backend.services.token_crypto.get_settings")
    def test_empty_string_noop(self, mock_get_settings):
        """Empty strings should pass through without encryption."""
        mock_get_settings.return_value = _mock_settings()
        assert encrypt_token("") == ""
        assert decrypt_token("") == ""

    @patch("backend.services.token_crypto.get_settings")
    def test_missing_key_raises(self, mock_get_settings):
        """An empty TOKEN_ENC_KEY should raise RuntimeError."""
        mock_get_settings.return_value = _mock_settings("")
        with pytest.raises(RuntimeError, match="TOKEN_ENC_KEY is not set"):
            encrypt_token("x")

    @patch("backend.services.token_crypto.get_settings")
    def test_fernet_cached(self, mock_get_settings):
        """_fernet() should return the same instance on repeated calls (lru_cache)."""
        mock_get_settings.return_value = _mock_settings()
        first = _fernet()
        second = _fernet()
        assert first is second
