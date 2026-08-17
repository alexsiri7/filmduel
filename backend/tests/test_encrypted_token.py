"""Tests for the EncryptedToken descriptor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.db_models import EncryptedToken


class TestEncryptedToken:
    def test_set_encrypts_value(self):
        """Setting via descriptor should call encrypt_token and store on enc attr."""
        descriptor = EncryptedToken("_enc_field")
        obj = MagicMock()

        with patch("backend.services.token_crypto.encrypt_token", return_value="encrypted_val") as mock_enc:
            descriptor.__set__(obj, "plaintext")

        mock_enc.assert_called_once_with("plaintext")
        assert obj._enc_field == "encrypted_val"

    def test_get_decrypts_value(self):
        """Getting via descriptor should call decrypt_token on the enc attr."""
        descriptor = EncryptedToken("_enc_field")
        obj = MagicMock()
        obj._enc_field = "encrypted_val"

        with patch("backend.services.token_crypto.decrypt_token", return_value="plaintext") as mock_dec:
            result = descriptor.__get__(obj, type(obj))

        mock_dec.assert_called_once_with("encrypted_val")
        assert result == "plaintext"

    def test_class_level_access_returns_descriptor(self):
        """Accessing on the class (obj=None) should return the descriptor itself."""
        descriptor = EncryptedToken("_enc_field")
        result = descriptor.__get__(None, MagicMock)
        assert result is descriptor
