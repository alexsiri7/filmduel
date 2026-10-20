"""Unit tests for _rekey and _make_fernets helpers in migration 020."""

from __future__ import annotations

import importlib
import importlib.util
import pathlib

import pytest
from cryptography.fernet import InvalidToken

# Migration module name starts with a digit, so we must use importlib
_migration_path = (
    pathlib.Path(__file__).parent.parent
    / "migrations"
    / "versions"
    / "020_rekey_tokens_hkdf.py"
)
_spec = importlib.util.spec_from_file_location("migration_020", _migration_path)
_migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_migration)
_make_fernets = _migration._make_fernets
_rekey = _migration._rekey

_spec_028 = importlib.util.spec_from_file_location(
    "migration_028", _migration_path.with_name("028_rekey_tokens_per_purpose.py")
)
_migration_028 = importlib.util.module_from_spec(_spec_028)
_spec_028.loader.exec_module(_migration_028)

TEST_KEY = "a-very-long-test-key-that-is-at-least-32-characters"


class TestMakeFernets:
    def test_old_and_new_keys_differ(self):
        """SHA-256 and HKDF derivations must produce different keys."""
        old, new = _make_fernets(TEST_KEY)
        # Encrypt with old; new should not be able to decrypt it
        ct = old.encrypt(b"probe")
        with pytest.raises(InvalidToken):
            new.decrypt(ct)

    def test_new_key_is_the_shared_key_028_rekeys_from(self):
        """The HKDF key 020 writes must be the one 028 reads as its source."""
        _, new_fernet = _make_fernets(TEST_KEY)
        shared_028, _, _ = _migration_028._make_fernets(TEST_KEY)
        ciphertext = new_fernet.encrypt(b"alignment-check")
        assert shared_028.decrypt(ciphertext) == b"alignment-check"


class TestRekey:
    def setup_method(self):
        self.old, self.new = _make_fernets(TEST_KEY)

    def test_happy_path_re_encrypts(self):
        """A token encrypted with old key is re-encrypted with new key."""
        plaintext = "oauth-token-abc"
        old_ciphertext = self.old.encrypt(plaintext.encode()).decode()
        result = _rekey(old_ciphertext, self.old, self.new)
        # Result must decrypt with new key
        assert self.new.decrypt(result.encode()) == plaintext.encode()
        # Result must NOT decrypt with old key
        with pytest.raises(InvalidToken):
            self.old.decrypt(result.encode())

    def test_idempotent_already_rekeyed(self):
        """A token already encrypted with new key is returned unchanged."""
        plaintext = "oauth-token-abc"
        new_ciphertext = self.new.encrypt(plaintext.encode()).decode()
        result = _rekey(new_ciphertext, self.old, self.new)
        assert result == new_ciphertext

    def test_none_passthrough(self):
        """None values are returned as-is (user has no token)."""
        assert _rekey(None, self.old, self.new) is None

    def test_empty_string_passthrough(self):
        """Empty strings are returned as-is."""
        assert _rekey("", self.old, self.new) == ""

    def test_corrupt_token_raises_runtime_error(self):
        """A token that can't be decrypted by either key raises RuntimeError."""
        with pytest.raises(RuntimeError, match="TOKEN_ENC_KEY matches"):
            _rekey("not-valid-ciphertext", self.old, self.new)
