"""Unit tests for backend/utils/tokens.py."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

from backend.services.token_crypto import _fernet
from backend.utils.tokens import decode_pair_token, encode_pair_token


@pytest.fixture(autouse=True)
def _clear_fernet_cache():
    """Clear the cached Fernet instance before each test."""
    _fernet.cache_clear()
    yield
    _fernet.cache_clear()


def _mock_settings(key: str = "a-very-long-test-key-that-is-at-least-32-characters"):
    s = MagicMock()
    s.TOKEN_ENC_KEY = key
    return s


class TestEncodePairToken:
    @patch("backend.services.token_crypto.get_settings")
    def test_returns_non_empty_string(self, mock_settings):
        """encode_pair_token returns a non-empty opaque string."""
        mock_settings.return_value = _mock_settings()
        token = encode_pair_token(str(uuid.uuid4()), str(uuid.uuid4()))
        assert isinstance(token, str)
        assert len(token) > 0

    @patch("backend.services.token_crypto.get_settings")
    def test_output_is_not_plaintext(self, mock_settings):
        """The token should not contain the raw UUIDs in plaintext."""
        mock_settings.return_value = _mock_settings()
        id_a = str(uuid.uuid4())
        id_b = str(uuid.uuid4())
        token = encode_pair_token(id_a, id_b)
        assert id_a not in token
        assert id_b not in token


class TestDecodePairToken:
    @patch("backend.services.token_crypto.get_settings")
    def test_roundtrip(self, mock_settings):
        """encode then decode returns the original ID set."""
        mock_settings.return_value = _mock_settings()
        id_a = str(uuid.uuid4())
        id_b = str(uuid.uuid4())
        token = encode_pair_token(id_a, id_b)
        result = decode_pair_token(token)
        assert result == {id_a, id_b}

    @patch("backend.services.token_crypto.get_settings")
    def test_decode_is_order_independent(self, mock_settings):
        """Pair set is unordered — encode(a,b) and encode(b,a) decode identically."""
        mock_settings.return_value = _mock_settings()
        id_a, id_b = str(uuid.uuid4()), str(uuid.uuid4())
        assert decode_pair_token(encode_pair_token(id_a, id_b)) == decode_pair_token(
            encode_pair_token(id_b, id_a)
        )

    @patch("backend.services.token_crypto.get_settings")
    def test_invalid_ciphertext_returns_none(self, mock_settings):
        """A garbage token (not valid Fernet ciphertext) returns None."""
        mock_settings.return_value = _mock_settings()
        # RuntimeError from wrong/garbled ciphertext is caught and returns None
        assert decode_pair_token("not-a-valid-token") is None

    @patch("backend.services.token_crypto.get_settings")
    def test_token_with_too_many_parts_returns_none(self, mock_settings):
        """A token that decrypts to 3 comma-separated parts returns None."""
        from backend.services.token_crypto import encrypt_token

        mock_settings.return_value = _mock_settings()
        token = encrypt_token("a,b,c")
        assert decode_pair_token(token) is None

    @patch("backend.services.token_crypto.get_settings")
    def test_token_with_one_part_returns_none(self, mock_settings):
        """A token that decrypts to a single value (no comma) returns None."""
        from backend.services.token_crypto import encrypt_token

        mock_settings.return_value = _mock_settings()
        token = encrypt_token("only-one-value")
        assert decode_pair_token(token) is None

    @patch("backend.services.token_crypto.get_settings")
    def test_wrong_key_returns_none(self, mock_settings):
        """A token encrypted with a different key returns None (decryption failure, not config error)."""
        mock_settings.return_value = _mock_settings("key-a-long-enough-for-validation-32char")
        id_a, id_b = str(uuid.uuid4()), str(uuid.uuid4())
        token = encode_pair_token(id_a, id_b)

        _fernet.cache_clear()
        mock_settings.return_value = _mock_settings("key-b-long-enough-for-validation-32char")
        # RuntimeError("Token decryption failed") is caught and returns None
        assert decode_pair_token(token) is None

    @patch("backend.services.token_crypto.get_settings")
    def test_missing_key_reraises_runtime_error(self, mock_settings):
        """A missing TOKEN_ENC_KEY raises RuntimeError (not swallowed as 400)."""
        mock_settings.return_value = _mock_settings("")
        with pytest.raises(RuntimeError, match="TOKEN_ENC_KEY is not set"):
            decode_pair_token("any-token")
