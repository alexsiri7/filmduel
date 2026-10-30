"""Unit tests for Settings validators."""

import hashlib
import logging
import os
import secrets
import ssl
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from pydantic import ValidationError

import backend.config
from backend.config import (
    Settings,
    database_connect_args,
    is_cleartext_public_redis_uri,
)
from backend.config import _PROXY_PLATFORM_ENV_VARS as _PROXY_PLATFORM_ENV_VARS_PROD


def _make_settings(**overrides) -> Settings:
    defaults = {
        "SECRET_KEY": "test-secret-key-for-unit-tests!!",
        "TRAKT_CLIENT_ID": "",
        "TRAKT_CLIENT_SECRET": "",
        "DATABASE_URL": "postgresql+asyncpg://localhost/test",
        # A public origin, so tests that set a platform env var are not tripped
        # by the AUD-23 loopback-origin check (TestCorsLoopbackFailClosed covers it).
        "CORS_ORIGINS": ["https://filmduel.example.com"],
    }
    defaults.update(overrides)
    return Settings(**defaults)


# Fixed, generated-looking keys (token_hex output shape: 16 distinct digits).
_KEY_32 = "3f9a0c7d1e5b8264a9f0c3d7e1b5a826"
_KEY_64 = _KEY_32 + "c41e8f2a7d0b9c536e1f4a8d2b7c0e95"


class TestKeyCharacterVariety:
    """AUD-28 (#710): a long key must also vary, not just be long."""

    @pytest.mark.parametrize("field", ["SECRET_KEY", "TOKEN_ENC_KEY"])
    @pytest.mark.parametrize(
        "key",
        ["a" * 32, "x" * 64, "ab" * 20],
    )
    def test_low_variety_key_rejected(self, field, key):
        with pytest.raises(ValidationError, match="distinct characters"):
            _make_settings(**{field: key})

    @pytest.mark.parametrize("field", ["SECRET_KEY", "TOKEN_ENC_KEY"])
    def test_five_distinct_rejected_six_accepted(self, field):
        with pytest.raises(ValidationError, match="only 5 distinct"):
            _make_settings(**{field: "12345" * 7})
        s = _make_settings(**{field: "123456" * 6})
        assert getattr(s, field) == "123456" * 6

    @pytest.mark.parametrize("field", ["SECRET_KEY", "TOKEN_ENC_KEY"])
    @pytest.mark.parametrize(
        "make",
        [
            lambda: secrets.token_hex(32),
            lambda: secrets.token_hex(16),
            lambda: secrets.token_urlsafe(32),
        ],
    )
    def test_generated_secrets_accepted(self, field, make):
        for _ in range(200):
            key = make()
            assert getattr(_make_settings(**{field: key}), field) == key

    def test_ci_and_test_suite_secrets_accepted(self):
        for key in (
            "ci-test-secret-key-not-for-production",
            "test-secret-key-for-unit-tests!!",
            "test-secret-key-for-unit-tests-32b",
        ):
            _make_settings(SECRET_KEY=key, TOKEN_ENC_KEY=key)

    def test_error_does_not_echo_the_key(self):
        key = "ab" * 20
        with pytest.raises(ValidationError) as exc:
            _make_settings(SECRET_KEY=key)
        assert key not in str(exc.value)


class TestSecretKeyValidation:
    def test_valid_32_char_key_accepted(self):
        s = _make_settings(SECRET_KEY=_KEY_32)
        assert s.SECRET_KEY == _KEY_32

    def test_valid_long_key_accepted(self):
        s = _make_settings(SECRET_KEY=_KEY_64)
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

    @pytest.mark.parametrize(
        "origin",
        [
            "https://filmduel.example.com/",
            "https://filmduel.example.com/app",
            "https://filmduel.example.com?x=1",
            "https://filmduel.example.com#frag",
            "filmduel.example.com",
            "https://",
            "https://user:pass@filmduel.example.com",
            "https://admin@filmduel.example.com",
        ],
    )
    def test_non_bare_origin_rejected(self, origin):
        """SEC-25 (#797): a browser Origin is scheme://host[:port] only."""
        with pytest.raises(ValidationError, match="scheme://host\\[:port\\]"):
            _make_settings(CORS_ORIGINS=["https://ok.example.com", origin])

    @pytest.mark.parametrize(
        "origin",
        [
            "https://user:hunter2@filmduel.example.com",
            "https://user:hun@ter2@filmduel.example.com",
            "https://user:hun/ter2@filmduel.example.com",
            "user:hunter2@filmduel.example.com",
        ],
    )
    def test_rejected_userinfo_not_echoed(self, origin):
        """Startup errors reach container logs and must not print the credential."""
        with pytest.raises(ValidationError) as exc:
            _make_settings(CORS_ORIGINS=[origin])
        assert "***@filmduel.example.com" in str(exc.value)
        assert "hun" not in str(exc.value)

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


class TestLlmConcurrencyBound:
    """LLM_MAX_CONCURRENT must leave a DB connection free (AUD-01)."""

    def test_default_below_pool_capacity(self):
        s = _make_settings()
        assert s.LLM_MAX_CONCURRENT < backend.config.DB_POOL_SIZE + backend.config.DB_MAX_OVERFLOW

    def test_one_below_pool_capacity_accepted(self):
        capacity = backend.config.DB_POOL_SIZE + backend.config.DB_MAX_OVERFLOW
        s = _make_settings(LLM_MAX_CONCURRENT=capacity - 1)
        assert s.LLM_MAX_CONCURRENT == capacity - 1

    def test_equal_to_pool_capacity_rejected(self):
        capacity = backend.config.DB_POOL_SIZE + backend.config.DB_MAX_OVERFLOW
        with pytest.raises(ValidationError, match="below the DB pool capacity"):
            _make_settings(LLM_MAX_CONCURRENT=capacity)

    def test_shrinking_the_pool_tightens_the_bound(self, monkeypatch):
        monkeypatch.setattr(backend.config, "DB_MAX_OVERFLOW", 0)
        with pytest.raises(ValidationError, match="below the DB pool capacity"):
            _make_settings(LLM_MAX_CONCURRENT=backend.config.DB_POOL_SIZE)


class TestLlmBaseUrl:
    """LLM_BASE_URL receives LLM_API_KEY as a bearer token, so it must be https."""

    def test_default_accepted(self):
        assert _make_settings().LLM_BASE_URL.startswith("https://")

    def test_https_override_accepted(self):
        s = _make_settings(LLM_BASE_URL="https://openrouter.ai/api/v1")
        assert s.LLM_BASE_URL == "https://openrouter.ai/api/v1"

    @pytest.mark.parametrize(
        "url", ["http://router.requesty.ai/v1", "router.requesty.ai/v1", ""]
    )
    def test_non_https_rejected(self, url):
        with pytest.raises(ValidationError, match="LLM_BASE_URL must use https"):
            _make_settings(LLM_BASE_URL=url)


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
        s = _make_settings(TOKEN_ENC_KEY=_KEY_32)
        assert s.TOKEN_ENC_KEY == _KEY_32

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
        s = _make_settings(TOKEN_ENC_KEY=_KEY_64)
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
            TOKEN_ENC_KEY=_KEY_32,
            TRAKT_CLIENT_ID="some-trakt-client-id",
        )
        assert s.TOKEN_ENC_KEY == _KEY_32

    def test_valid_key_accepted_when_simkl_client_id_set(self):
        s = _make_settings(
            TOKEN_ENC_KEY=_KEY_32,
            SIMKL_CLIENT_ID="some-simkl-client-id",
            TRAKT_CLIENT_ID="",
        )
        assert s.TOKEN_ENC_KEY == _KEY_32

    def test_valid_key_accepted_when_both_oauth_providers_set(self):
        s = _make_settings(
            TOKEN_ENC_KEY=_KEY_32,
            TRAKT_CLIENT_ID="some-trakt-client-id",
            SIMKL_CLIENT_ID="some-simkl-client-id",
        )
        assert s.TOKEN_ENC_KEY == _KEY_32


class TestSmokeSessionSettings:
    """#794: the smoke-session key is optional, paired with its user, and not SECRET_KEY."""

    _USER_ID = "550E8400-E29B-41D4-A716-446655440000"

    def test_both_unset_accepted(self):
        s = _make_settings()
        assert (s.SMOKE_SESSION_KEY, s.SMOKE_USER_ID) == ("", "")

    def test_both_set_accepted_and_user_id_canonicalised(self):
        s = _make_settings(SMOKE_SESSION_KEY=_KEY_32, SMOKE_USER_ID=self._USER_ID)
        assert s.SMOKE_SESSION_KEY == _KEY_32
        assert s.SMOKE_USER_ID == self._USER_ID.lower()

    @pytest.mark.parametrize(
        "overrides",
        [{"SMOKE_SESSION_KEY": _KEY_32}, {"SMOKE_USER_ID": _USER_ID}],
    )
    def test_one_without_the_other_rejected(self, overrides):
        with pytest.raises(ValidationError, match="must be set together"):
            _make_settings(**overrides)

    def test_key_equal_to_secret_key_rejected(self):
        with pytest.raises(ValidationError, match="must differ from SECRET_KEY"):
            _make_settings(
                SECRET_KEY=_KEY_32, SMOKE_SESSION_KEY=_KEY_32, SMOKE_USER_ID=self._USER_ID
            )

    @pytest.mark.parametrize(
        ("key", "message"), [("a" * 32, "distinct characters"), ("changeme", "placeholder")]
    )
    def test_weak_key_rejected(self, key, message):
        with pytest.raises(ValidationError, match=message):
            _make_settings(SMOKE_SESSION_KEY=key, SMOKE_USER_ID=self._USER_ID)

    def test_non_uuid_user_id_rejected(self):
        with pytest.raises(ValidationError, match="SMOKE_USER_ID must be a UUID"):
            _make_settings(SMOKE_SESSION_KEY=_KEY_32, SMOKE_USER_ID="smoke-user")


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


class TestDatabaseConnectArgs:
    """On a hosted platform the DB connection requires TLS verified against
    Supabase's pinned root CA; off-platform asyncpg's default is kept (AUD-04, #686)."""

    _NO_PREPARED_STATEMENTS = {"statement_cache_size": 0, "prepared_statement_cache_size": 0}

    def _only_platform(self, monkeypatch, var: str | None):
        for other in _PROXY_PLATFORM_ENV_VARS_PROD:
            monkeypatch.delenv(other, raising=False)
        if var is not None:
            monkeypatch.setenv(var, "set")

    def test_no_tls_override_off_platform(self, monkeypatch):
        self._only_platform(monkeypatch, None)
        assert database_connect_args() == self._NO_PREPARED_STATEMENTS

    @pytest.mark.parametrize("var", _PROXY_PLATFORM_ENV_VARS_PROD)
    def test_verified_tls_on_each_known_platform(self, monkeypatch, var):
        self._only_platform(monkeypatch, var)
        args = database_connect_args()
        ctx = args.pop("ssl")
        assert args == self._NO_PREPARED_STATEMENTS
        assert isinstance(ctx, ssl.SSLContext)
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
        (ca,) = ctx.get_ca_certs()
        assert (("commonName", "Supabase Root 2021 CA"),) in ca["subject"]

    def test_strict_x509_disabled_for_supabase_chain(self, monkeypatch):
        """Supabase's intermediate CA lacks keyUsage, so strict mode would reject the chain."""
        self._only_platform(monkeypatch, "RAILWAY_ENVIRONMENT")
        ctx = database_connect_args()["ssl"]
        assert not (ctx.verify_flags & ssl.VERIFY_X509_STRICT)

    def test_pinned_ca_fingerprint(self):
        der = ssl.PEM_cert_to_DER_cert(backend.config._SUPABASE_ROOT_CA.read_text())
        assert (
            hashlib.sha256(der).hexdigest()
            == "807025ad50d4ed219d2c9c7d299c004f824eb00cf7f65afef607d07b72e6cafa"
        )


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


async def _run_lifespan(test_settings, caplog):
    from backend import main as main_mod

    with patch.object(main_mod, "settings", test_settings), \
         patch.object(main_mod._scheduler, "start"), \
         patch.object(main_mod._scheduler, "shutdown"), \
         caplog.at_level(logging.INFO, logger="backend.main"):
        async with main_mod.lifespan(FastAPI()):
            pass


class TestRateLimitStorageStartupWarning:
    """lifespan() reports whether rate-limit counters are durable/shared."""

    _PROXY_PLATFORM_ENV_VARS = _PROXY_PLATFORM_ENV_VARS_PROD

    @pytest.mark.asyncio
    async def test_warning_when_platform_env_and_uri_unset(self, monkeypatch, caplog):
        monkeypatch.setenv("RAILWAY_ENVIRONMENT", "production")
        for var in self._PROXY_PLATFORM_ENV_VARS:
            if var != "RAILWAY_ENVIRONMENT":
                monkeypatch.delenv(var, raising=False)

        # explicit so the SEC-11 fail-closed check doesn't trip on the platform var
        await _run_lifespan(
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
        await _run_lifespan(
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

        await _run_lifespan(_make_settings(RATE_LIMIT_STORAGE_URI=""), caplog)

        assert "rate_limit_storage" not in caplog.text

    @pytest.mark.asyncio
    async def test_info_logged_without_platform_env_when_uri_set(self, monkeypatch, caplog):
        for var in self._PROXY_PLATFORM_ENV_VARS:
            monkeypatch.delenv(var, raising=False)

        await _run_lifespan(
            _make_settings(RATE_LIMIT_STORAGE_URI="redis://127.0.0.1:1/0"), caplog
        )

        assert "rate_limit_storage_unset" not in caplog.text
        assert any(
            r.levelno == logging.INFO and "rate_limit_storage: redis" in r.message
            for r in caplog.records
        ), "Redis confirmation must not depend on hosted-platform detection"
        assert "127.0.0.1:1" not in caplog.text, "URI must never be logged"

    @pytest.mark.asyncio
    async def test_cleartext_warning_for_public_host_never_logs_uri(self, monkeypatch, caplog):
        for var in self._PROXY_PLATFORM_ENV_VARS:
            monkeypatch.delenv(var, raising=False)

        await _run_lifespan(
            _make_settings(
                RATE_LIMIT_STORAGE_URI="redis://default:s3cret@redis.example.com:6379/0"
            ),
            caplog,
        )

        assert any(
            r.levelno == logging.WARNING and "rate_limit_storage_cleartext" in r.message
            for r in caplog.records
        ), "Expected rate_limit_storage_cleartext warning"
        assert "s3cret" not in caplog.text, "URI must never be logged"
        assert "redis.example.com" not in caplog.text, "URI must never be logged"

    @pytest.mark.asyncio
    async def test_no_cleartext_warning_for_tls_uri(self, monkeypatch, caplog):
        for var in self._PROXY_PLATFORM_ENV_VARS:
            monkeypatch.delenv(var, raising=False)

        await _run_lifespan(
            _make_settings(RATE_LIMIT_STORAGE_URI="rediss://redis.example.com:6380/0"),
            caplog,
        )

        assert "rate_limit_storage_cleartext" not in caplog.text

    @pytest.mark.asyncio
    async def test_no_cleartext_warning_for_private_host(self, monkeypatch, caplog):
        """The recommended Railway URI (${{Redis.REDIS_URL}}) is cleartext but private."""
        for var in self._PROXY_PLATFORM_ENV_VARS:
            monkeypatch.delenv(var, raising=False)

        await _run_lifespan(
            _make_settings(
                RATE_LIMIT_STORAGE_URI="redis://default:pw@redis.railway.internal:6379/0"
            ),
            caplog,
        )

        assert "rate_limit_storage: redis" in caplog.text
        assert "rate_limit_storage_cleartext" not in caplog.text


class TestCleartextPublicRedisUri:
    """SEC-26 (#798): plain redis:// is flagged only when the host is not recognisably private."""

    @pytest.mark.parametrize(
        "uri",
        [
            "redis://default:pw@redis.railway.internal:6379",
            "redis://10.0.0.5:6379/0",
            "redis://[fd12::1]:6379",
            "redis://redis:6379",
            "redis://127.0.0.1:1/0",
            "redis://localhost",
            "redis://",
            "rediss://redis.example.com:6380",
            "redis+unix:///tmp/redis.sock",
        ],
    )
    def test_not_flagged(self, uri):
        assert not is_cleartext_public_redis_uri(uri)

    @pytest.mark.parametrize(
        "uri",
        [
            "redis://default:pw@monorail.proxy.rlwy.net:12345",
            "redis://redis.example.com:6379",
            "redis://8.8.8.8:6379",
            # an IPv6 literal has no dot, so it must not pass as a single-label name
            "redis://[2606:4700::1]:6379",
        ],
    )
    def test_flagged(self, uri):
        assert is_cleartext_public_redis_uri(uri)


class TestTmdbAuthStartupWarning:
    """lifespan() warns when TMDB_API_KEY is a v3 key that must travel in the URL."""

    _V3_KEY = "0123456789abcdef0123456789abcdef"
    _V4_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJ0ZXN0In0.sig"

    @pytest.mark.asyncio
    async def test_warning_for_v3_key_never_logs_value(self, caplog):
        await _run_lifespan(_make_settings(TMDB_API_KEY=self._V3_KEY), caplog)

        assert any(
            r.levelno == logging.WARNING and "tmdb_v3_api_key" in r.message
            for r in caplog.records
        ), "Expected tmdb_v3_api_key warning"
        assert self._V3_KEY not in caplog.text, "Key must never be logged"

    @pytest.mark.asyncio
    async def test_no_warning_for_read_access_token(self, caplog):
        await _run_lifespan(_make_settings(TMDB_API_KEY=self._V4_TOKEN), caplog)

        assert "tmdb_v3_api_key" not in caplog.text

    @pytest.mark.asyncio
    async def test_no_warning_when_unset(self, caplog):
        await _run_lifespan(_make_settings(), caplog)

        assert "tmdb_v3_api_key" not in caplog.text


class TestCorsLoopbackFailClosed:
    """AUD-23 (#705) / SEC-25 (#797): on a hosted platform a loopback or plain-http
    CORS origin refuses to start."""

    _PROXY_PLATFORM_ENV_VARS = _PROXY_PLATFORM_ENV_VARS_PROD

    def _only_platform(self, monkeypatch, var: str | None, value: str = "set"):
        for other in self._PROXY_PLATFORM_ENV_VARS:
            monkeypatch.delenv(other, raising=False)
        if var is not None:
            monkeypatch.setenv(var, value)

    @pytest.mark.parametrize("var", _PROXY_PLATFORM_ENV_VARS_PROD)
    def test_unset_default_raises_on_each_platform(self, monkeypatch, var):
        """The localhost default (CORS_ORIGINS never configured) fails closed."""
        self._only_platform(monkeypatch, var)
        monkeypatch.delenv("CORS_ORIGINS", raising=False)

        with pytest.raises(ValidationError, match="cors_origins_loopback") as exc:
            Settings(
                SECRET_KEY="test-secret-key-for-unit-tests!!",
                DATABASE_URL="postgresql+asyncpg://localhost/test",
                BASE_URL="https://example.com",
                _env_file=None,
            )

        assert var in str(exc.value)

    @pytest.mark.parametrize(
        "origin",
        [
            "http://localhost:5173",
            "https://LOCALHOST",
            "http://app.localhost:8080",
            "http://127.0.0.1:8000",
            "http://127.1.2.3",
            "http://[::1]:3000",
            "http://0.0.0.0:8000",
        ],
    )
    def test_explicit_loopback_origin_raises(self, monkeypatch, origin):
        self._only_platform(monkeypatch, "RAILWAY_ENVIRONMENT", "production")

        with pytest.raises(ValidationError, match="cors_origins_loopback"):
            _make_settings(
                BASE_URL="https://example.com",
                CORS_ORIGINS=["https://filmduel.example.com", origin],
            )

    def test_public_origins_boot_on_platform(self, monkeypatch):
        self._only_platform(monkeypatch, "RAILWAY_ENVIRONMENT", "production")

        s = _make_settings(
            BASE_URL="https://example.com",
            CORS_ORIGINS="https://filmduel.example.com,https://localhost-fans.example.org",
        )

        assert s.CORS_ORIGINS == [
            "https://filmduel.example.com",
            "https://localhost-fans.example.org",
        ]

    @pytest.mark.parametrize(
        "cors_origins",
        [
            "http://filmduel.example.com,https://filmduel.example.com",
            "https://filmduel.example.com,http://filmduel.example.com",
        ],
    )
    @pytest.mark.parametrize("var", _PROXY_PLATFORM_ENV_VARS_PROD)
    def test_plain_http_public_origin_raises_on_each_platform(
        self, monkeypatch, var, cors_origins
    ):
        """SEC-25 (#797): hosted platforms terminate TLS, so every origin must be https."""
        self._only_platform(monkeypatch, var)

        with pytest.raises(ValidationError, match="cors_origins_insecure") as exc:
            _make_settings(BASE_URL="https://example.com", CORS_ORIGINS=cors_origins)

        assert var in str(exc.value)

    def test_plain_http_public_origin_allowed_off_platform(self, monkeypatch):
        self._only_platform(monkeypatch, None)

        s = _make_settings(CORS_ORIGINS="http://filmduel.example.com")

        assert s.CORS_ORIGINS == ["http://filmduel.example.com"]

    def test_localhost_default_allowed_off_platform(self, monkeypatch):
        """Local dev keeps the localhost default."""
        self._only_platform(monkeypatch, None)
        monkeypatch.delenv("CORS_ORIGINS", raising=False)

        s = Settings(
            SECRET_KEY="test-secret-key-for-unit-tests!!",
            DATABASE_URL="postgresql+asyncpg://localhost/test",
            _env_file=None,
        )

        assert "http://localhost:5173" in s.CORS_ORIGINS
