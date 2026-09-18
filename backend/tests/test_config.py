"""Unit tests for Settings validators."""

import logging
import os
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from backend.config import Settings
from backend.config import _PROXY_PLATFORM_ENV_VARS as _PROXY_PLATFORM_ENV_VARS_PROD


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

    def test_plain_url_env_var_accepted(self, monkeypatch):
        """A plain URL (not JSON) in CORS_ORIGINS env var must be accepted.

        pydantic-settings ≥2.4 raises SettingsError when it can't JSON-decode a
        list field; _TolerantEnvSource falls back to the raw string so the
        mode='before' validator can split it by comma instead.
        """
        monkeypatch.setenv("CORS_ORIGINS", "https://example.com")
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-unit-tests!!")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost/test")
        monkeypatch.setenv("TRAKT_CLIENT_ID", "")
        s = Settings()
        assert s.CORS_ORIGINS == ["https://example.com"]

    def test_json_array_env_var_accepted(self, monkeypatch):
        """A JSON-array CORS_ORIGINS env var is also accepted."""
        monkeypatch.setenv("CORS_ORIGINS", '["https://example.com","https://other.com"]')
        monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-unit-tests!!")
        monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://localhost/test")
        monkeypatch.setenv("TRAKT_CLIENT_ID", "")
        s = Settings()
        assert s.CORS_ORIGINS == ["https://example.com", "https://other.com"]


class TestRetentionDefaults:
    def test_duel_retention_days_default(self):
        """DUEL_RETENTION_DAYS defaults to 180 (compliance window)."""
        s = _make_settings()
        assert s.DUEL_RETENTION_DAYS == 180

    def test_swipe_retention_days_default(self):
        """SWIPE_RETENTION_DAYS defaults to 180 (compliance window)."""
        s = _make_settings()
        assert s.SWIPE_RETENTION_DAYS == 180

    def test_duel_retention_days_override(self):
        s = _make_settings(DUEL_RETENTION_DAYS=90)
        assert s.DUEL_RETENTION_DAYS == 90

    def test_swipe_retention_days_override(self):
        s = _make_settings(SWIPE_RETENTION_DAYS=365)
        assert s.SWIPE_RETENTION_DAYS == 365

    def test_purge_schedule_hour_default(self):
        """PURGE_SCHEDULE_HOUR defaults to 2 UTC (low-traffic window)."""
        s = _make_settings()
        assert s.PURGE_SCHEDULE_HOUR == 2

    def test_purge_schedule_hour_override(self):
        s = _make_settings(PURGE_SCHEDULE_HOUR=3)
        assert s.PURGE_SCHEDULE_HOUR == 3

    def test_purge_schedule_hour_zero_valid(self):
        s = _make_settings(PURGE_SCHEDULE_HOUR=0)
        assert s.PURGE_SCHEDULE_HOUR == 0

    def test_purge_schedule_hour_23_valid(self):
        s = _make_settings(PURGE_SCHEDULE_HOUR=23)
        assert s.PURGE_SCHEDULE_HOUR == 23

    def test_purge_schedule_hour_negative_rejected(self):
        with pytest.raises(ValidationError):
            _make_settings(PURGE_SCHEDULE_HOUR=-1)

    def test_purge_schedule_hour_24_rejected(self):
        with pytest.raises(ValidationError):
            _make_settings(PURGE_SCHEDULE_HOUR=24)


class TestTokenEncKeyValidation:
    def test_empty_string_accepted_without_oauth(self):
        """Empty TOKEN_ENC_KEY is allowed when no OAuth client IDs are configured."""
        s = _make_settings(TOKEN_ENC_KEY="", TRAKT_CLIENT_ID="", SIMKL_CLIENT_ID="")
        assert s.TOKEN_ENC_KEY == ""

    def test_valid_32_char_key_accepted(self):
        s = _make_settings(TOKEN_ENC_KEY="a" * 32)
        assert s.TOKEN_ENC_KEY == "a" * 32

    def test_31_char_key_rejected(self):
        with pytest.raises(ValidationError, match="at least 32 characters"):
            _make_settings(TOKEN_ENC_KEY="a" * 31)

    def test_placeholder_change_me_rejected(self):
        with pytest.raises(ValidationError, match="placeholder"):
            _make_settings(TOKEN_ENC_KEY="change-me")

    def test_placeholder_change_me_in_production_rejected(self):
        with pytest.raises(ValidationError, match="placeholder"):
            _make_settings(TOKEN_ENC_KEY="change-me-in-production")

    def test_placeholder_secret_rejected(self):
        with pytest.raises(ValidationError, match="placeholder"):
            _make_settings(TOKEN_ENC_KEY="secret")

    def test_placeholder_is_case_insensitive(self):
        with pytest.raises(ValidationError, match="placeholder"):
            _make_settings(TOKEN_ENC_KEY="SECRET")

    def test_valid_long_key_accepted(self):
        s = _make_settings(TOKEN_ENC_KEY="x" * 64)
        assert len(s.TOKEN_ENC_KEY) == 64

    def test_empty_key_rejected_when_trakt_client_id_set(self):
        with pytest.raises(ValidationError, match="TOKEN_ENC_KEY must be set"):
            _make_settings(
                TOKEN_ENC_KEY="",
                TRAKT_CLIENT_ID="some-trakt-client-id",
            )

    def test_empty_key_rejected_when_simkl_client_id_set(self):
        with pytest.raises(ValidationError, match="TOKEN_ENC_KEY must be set"):
            _make_settings(
                TOKEN_ENC_KEY="",
                SIMKL_CLIENT_ID="some-simkl-client-id",
                TRAKT_CLIENT_ID="",
            )

    def test_valid_key_accepted_when_trakt_client_id_set(self):
        s = _make_settings(
            TOKEN_ENC_KEY="a" * 32,
            TRAKT_CLIENT_ID="some-trakt-client-id",
        )
        assert s.TOKEN_ENC_KEY == "a" * 32

    def test_valid_key_accepted_when_simkl_client_id_set(self):
        s = _make_settings(
            TOKEN_ENC_KEY="a" * 32,
            SIMKL_CLIENT_ID="some-simkl-client-id",
            TRAKT_CLIENT_ID="",
        )
        assert s.TOKEN_ENC_KEY == "a" * 32

    def test_valid_key_accepted_when_both_oauth_providers_set(self):
        s = _make_settings(
            TOKEN_ENC_KEY="a" * 32,
            TRAKT_CLIENT_ID="some-trakt-client-id",
            SIMKL_CLIENT_ID="some-simkl-client-id",
        )
        assert s.TOKEN_ENC_KEY == "a" * 32


class TestCookieSecure:
    def test_defaults_to_is_https_when_unset(self):
        """cookie_secure mirrors is_https when SECURE_COOKIES is not set."""
        s = _make_settings(BASE_URL="http://localhost:8000")
        assert s.cookie_secure is False

        s_https = _make_settings(BASE_URL="https://example.com")
        assert s_https.cookie_secure is True

    def test_explicit_true_overrides_http_base_url(self):
        """SECURE_COOKIES=true forces Secure flag even with http:// BASE_URL."""
        s = _make_settings(BASE_URL="http://localhost:8000", SECURE_COOKIES=True)
        assert s.cookie_secure is True

    def test_explicit_false_overrides_https_base_url(self):
        """SECURE_COOKIES=false disables Secure flag even with https:// BASE_URL."""
        s = _make_settings(BASE_URL="https://example.com", SECURE_COOKIES=False)
        assert s.cookie_secure is False


class TestDatabaseUrlValidation:
    def test_valid_database_url_accepted(self):
        s = _make_settings(DATABASE_URL="postgresql+asyncpg://user:pass@host:5432/db")
        assert s.DATABASE_URL == "postgresql+asyncpg://user:pass@host:5432/db"

    def test_hardcoded_localhost_default_rejected(self):
        with pytest.raises(ValidationError, match="hardcoded localhost default"):
            _make_settings(
                DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"
            )

    def test_empty_database_url_rejected(self):
        with pytest.raises(ValidationError, match="DATABASE_URL must be set"):
            _make_settings(DATABASE_URL="")

    def test_whitespace_only_database_url_rejected(self):
        with pytest.raises(ValidationError, match="DATABASE_URL must be set"):
            _make_settings(DATABASE_URL="   ")

    def test_missing_database_url_rejected(self, monkeypatch):
        """DATABASE_URL has no default so omitting it raises ValidationError."""
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(ValidationError, match="DATABASE_URL"):
            Settings(SECRET_KEY="test-secret-key-for-unit-tests!!")


class TestRateLimitStorageUriValidation:
    def test_defaults_to_empty(self):
        s = _make_settings()
        assert s.RATE_LIMIT_STORAGE_URI == ""

    def test_empty_string_accepted(self):
        s = _make_settings(RATE_LIMIT_STORAGE_URI="")
        assert s.RATE_LIMIT_STORAGE_URI == ""

    def test_whitespace_is_stripped(self):
        s = _make_settings(RATE_LIMIT_STORAGE_URI="  redis://h:6379/0 ")
        assert s.RATE_LIMIT_STORAGE_URI == "redis://h:6379/0"

    @pytest.mark.parametrize(
        "uri",
        [
            "redis://default:pw@host:6379/0",
            "rediss://host:6380/0",
            "redis+unix:///tmp/redis.sock",
        ],
    )
    def test_redis_schemes_accepted_verbatim(self, uri):
        s = _make_settings(RATE_LIMIT_STORAGE_URI=uri)
        assert s.RATE_LIMIT_STORAGE_URI == uri

    @pytest.mark.parametrize("uri", ["memcached://h:11211", "memory://", "h:6379"])
    def test_non_redis_uri_rejected(self, uri):
        with pytest.raises(ValidationError, match="RATE_LIMIT_STORAGE_URI"):
            _make_settings(RATE_LIMIT_STORAGE_URI=uri)


class TestCookieSecureFailClosed:
    """Settings() refuses to build when a TLS-proxy platform is detected and the
    Secure flag is neither explicit nor inferable from an https BASE_URL (SEC-11, #579)."""

    # Import from production module — single source of truth.
    # If a new platform is added to config.py, this reference auto-tracks it.
    _PROXY_PLATFORM_ENV_VARS = _PROXY_PLATFORM_ENV_VARS_PROD

    def _only_platform(self, monkeypatch, var: str | None, value: str = "set"):
        for other in self._PROXY_PLATFORM_ENV_VARS:
            monkeypatch.delenv(other, raising=False)
        if var is not None:
            monkeypatch.setenv(var, value)

    @pytest.mark.parametrize("var", _PROXY_PLATFORM_ENV_VARS_PROD)
    def test_raises_for_each_known_platform(self, monkeypatch, var):
        self._only_platform(monkeypatch, var)

        with pytest.raises(ValidationError, match="cookie_secure_unset") as exc:
            _make_settings(BASE_URL="http://localhost:8000", SECURE_COOKIES=None)

        assert var in str(exc.value)
        assert "SECURE_COOKIES=true" in str(exc.value)

    def test_boots_when_secure_cookies_explicitly_true(self, monkeypatch):
        self._only_platform(monkeypatch, "RAILWAY_ENVIRONMENT", "production")

        s = _make_settings(BASE_URL="http://localhost:8000", SECURE_COOKIES=True)

        assert s.cookie_secure is True

    def test_boots_when_secure_cookies_explicitly_false(self, monkeypatch):
        """An explicit false is an operator decision, not a missing one."""
        self._only_platform(monkeypatch, "RAILWAY_ENVIRONMENT", "production")

        s = _make_settings(BASE_URL="http://localhost:8000", SECURE_COOKIES=False)

        assert s.cookie_secure is False

    def test_boots_when_base_url_is_https(self, monkeypatch):
        self._only_platform(monkeypatch, "RAILWAY_ENVIRONMENT", "production")

        s = _make_settings(BASE_URL="https://example.com", SECURE_COOKIES=None)

        assert s.cookie_secure is True

    def test_boots_when_no_platform_env(self, monkeypatch):
        """Local dev (no platform var, http BASE_URL) is unaffected."""
        self._only_platform(monkeypatch, None)

        s = _make_settings(BASE_URL="http://localhost:8000", SECURE_COOKIES=None)

        assert s.cookie_secure is False

    def test_boots_when_platform_env_set_to_empty_string(self, monkeypatch):
        """Empty-string platform env var is not a detection (os.environ.get is falsy)."""
        self._only_platform(monkeypatch, "RAILWAY_ENVIRONMENT", "")

        s = _make_settings(BASE_URL="http://localhost:8000", SECURE_COOKIES=None)

        assert s.cookie_secure is False

    def test_first_matching_platform_env_var_is_reported(self, monkeypatch):
        """When multiple platform vars are set, the first one in tuple order is reported."""
        # RAILWAY_ENVIRONMENT precedes RENDER in _PROXY_PLATFORM_ENV_VARS
        self._only_platform(monkeypatch, "RAILWAY_ENVIRONMENT", "production")
        monkeypatch.setenv("RENDER", "true")

        with pytest.raises(ValidationError, match="RAILWAY_ENVIRONMENT"):
            _make_settings(BASE_URL="http://localhost:8000", SECURE_COOKIES=None)


class TestRateLimitStorageStartupWarning:
    """lifespan() reports whether rate-limit counters are durable/shared."""

    _PROXY_PLATFORM_ENV_VARS = _PROXY_PLATFORM_ENV_VARS_PROD

    async def _run_lifespan(self, test_settings, caplog):
        from backend import main as main_mod

        with patch.object(main_mod, "settings", test_settings), \
             patch.object(main_mod._scheduler, "start"), \
             patch.object(main_mod._scheduler, "shutdown"), \
             caplog.at_level(logging.INFO, logger="backend.main"):
            async with main_mod.lifespan(FastAPI()):
                pass

    @pytest.mark.asyncio
    async def test_warning_when_platform_env_and_uri_unset(self, monkeypatch, caplog):
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        for var in self._PROXY_PLATFORM_ENV_VARS:
            if var != "RAILWAY_ENVIRONMENT":
                monkeypatch.delenv(var, raising=False)

        # explicit so the SEC-11 fail-closed check doesn't trip on the platform var
        await self._run_lifespan(
            _make_settings(RATE_LIMIT_STORAGE_URI="", SECURE_COOKIES=True), caplog
        )

        assert any(
            r.levelno == logging.WARNING
            and "rate_limit_storage_unset" in r.message
            and "RAILWAY_ENVIRONMENT" in r.message
            for r in caplog.records
        ), "Expected rate_limit_storage_unset warning mentioning RAILWAY_ENVIRONMENT"

    @pytest.mark.asyncio
    async def test_info_and_no_warning_when_uri_set(self, monkeypatch, caplog):
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")

        # explicit so the SEC-11 fail-closed check doesn't trip on the platform var
        await self._run_lifespan(
            _make_settings(RATE_LIMIT_STORAGE_URI="redis://127.0.0.1:1/0", SECURE_COOKIES=True),
            caplog,
        )

        assert "rate_limit_storage_unset" not in caplog.text
        assert any(
            r.levelno == logging.INFO and "rate_limit_storage: redis" in r.message
            for r in caplog.records
        )
        assert "127.0.0.1:1" not in caplog.text, "URI must never be logged"

    @pytest.mark.asyncio
    async def test_no_warning_without_platform_env(self, monkeypatch, caplog):
        for var in self._PROXY_PLATFORM_ENV_VARS:
            monkeypatch.delenv(var, raising=False)

        await self._run_lifespan(_make_settings(RATE_LIMIT_STORAGE_URI=""), caplog)

        assert "rate_limit_storage" not in caplog.text

    @pytest.mark.asyncio
    async def test_info_logged_without_platform_env_when_uri_set(self, monkeypatch, caplog):
        for var in self._PROXY_PLATFORM_ENV_VARS:
            monkeypatch.delenv(var, raising=False)

        await self._run_lifespan(
            _make_settings(RATE_LIMIT_STORAGE_URI="redis://127.0.0.1:1/0"), caplog
        )

        assert "rate_limit_storage_unset" not in caplog.text
        assert any(
            r.levelno == logging.INFO and "rate_limit_storage: redis" in r.message
            for r in caplog.records
        ), "Redis confirmation must not depend on hosted-platform detection"
        assert "127.0.0.1:1" not in caplog.text, "URI must never be logged"
