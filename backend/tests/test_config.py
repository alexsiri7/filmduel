"""Unit tests for Settings.validate_secret_key."""

import pytest
from pydantic import ValidationError

from backend.config import Settings


def _make_settings(**overrides) -> Settings:
    defaults = {
        "SECRET_KEY": "test-secret-key-for-unit-tests!!",
        "TRAKT_CLIENT_ID": "",
        "TRAKT_CLIENT_SECRET": "",
        "DATABASE_URL": "postgresql+asyncpg://localhost/test",
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestSecretKeyValidation:
    def test_valid_32_char_key_accepted(self):
        s = _make_settings(SECRET_KEY="a" * 32)
        assert s.SECRET_KEY == "a" * 32

    def test_valid_long_key_accepted(self):
        s = _make_settings(SECRET_KEY="x" * 64)
        assert len(s.SECRET_KEY) == 64

    def test_31_char_key_rejected(self):
        with pytest.raises(ValidationError, match="at least 32 characters"):
            _make_settings(SECRET_KEY="a" * 31)

    def test_empty_key_rejected(self):
        with pytest.raises(ValidationError, match="at least 32 characters"):
            _make_settings(SECRET_KEY="")

    def test_placeholder_secret_rejected(self):
        with pytest.raises(ValidationError, match="placeholder"):
            _make_settings(SECRET_KEY="secret")

    def test_placeholder_changeme_rejected(self):
        with pytest.raises(ValidationError, match="placeholder"):
            _make_settings(SECRET_KEY="changeme")

    def test_placeholder_is_case_insensitive(self):
        with pytest.raises(ValidationError, match="placeholder"):
            _make_settings(SECRET_KEY="SECRET")

    def test_32_char_placeholder_prefix_is_not_rejected(self):
        """A 32-char key that isn't in the placeholder set passes."""
        key = "secret-but-padded-to-32-chars!!!"  # 32 chars, not in set
        s = _make_settings(SECRET_KEY=key)
        assert s.SECRET_KEY == key


class TestCorsOriginsValidation:
    def test_valid_origins_accepted(self):
        s = _make_settings(CORS_ORIGINS="http://localhost:5173,http://localhost:3000")
        assert s.CORS_ORIGINS == ["http://localhost:5173", "http://localhost:3000"]

    def test_whitespace_stripped(self):
        s = _make_settings(CORS_ORIGINS="http://localhost:5173, http://localhost:3000")
        assert s.CORS_ORIGINS == ["http://localhost:5173", "http://localhost:3000"]

    def test_trailing_comma_empty_entry_dropped(self):
        s = _make_settings(CORS_ORIGINS="http://localhost:5173,")
        assert s.CORS_ORIGINS == ["http://localhost:5173"]

    def test_wildcard_rejected(self):
        with pytest.raises(ValidationError, match="must not contain '\\*'"):
            _make_settings(CORS_ORIGINS="*")

    def test_wildcard_in_string_rejected(self):
        with pytest.raises(ValidationError, match="must not contain '\\*'"):
            _make_settings(CORS_ORIGINS="http://localhost:5173,*")

    def test_wildcard_in_list_rejected(self):
        with pytest.raises(ValidationError, match="must not contain '\\*'"):
            _make_settings(CORS_ORIGINS=["http://localhost:5173", "*"])

    def test_non_string_non_list_rejected(self):
        with pytest.raises(ValidationError, match="comma-separated string or list"):
            _make_settings(CORS_ORIGINS=42)

    def test_empty_string_rejected(self):
        with pytest.raises(ValidationError, match="at least one origin"):
            _make_settings(CORS_ORIGINS="")

    def test_only_commas_rejected(self):
        with pytest.raises(ValidationError, match="at least one origin"):
            _make_settings(CORS_ORIGINS=",,,")

    def test_list_input_accepted(self):
        s = _make_settings(CORS_ORIGINS=["http://localhost:5173"])
        assert s.CORS_ORIGINS == ["http://localhost:5173"]
