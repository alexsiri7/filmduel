"""Application configuration via environment variables."""

import os
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, EnvSettingsSource
from pydantic_settings.exceptions import SettingsError


class _TolerantEnvSource(EnvSettingsSource):
    """EnvSettingsSource that falls back to the raw string when a complex
    field value is not valid JSON.

    pydantic-settings ≥2.4 raises SettingsError for list/dict fields whose
    env-var value is not JSON (e.g. CORS_ORIGINS=https://foo.com rather than
    CORS_ORIGINS=["https://foo.com"]).  By catching that error and returning
    the raw value we let the ``mode="before"`` field validators handle
    comma-separated strings without requiring operators to wrap values in
    JSON array syntax.
    """

    def decode_complex_value(
        self, field_name: str, field_info: object, value: object
    ) -> object:
        try:
            return super().decode_complex_value(field_name, field_info, value)
        except (SettingsError, ValueError):
            return value  # raw string; field validator handles it


_LOCALHOST_DB_DEFAULT = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

# The only schemes the installed redis client (limits' RedisStorage) accepts.
_RATE_LIMIT_STORAGE_SCHEMES = ("redis://", "rediss://", "redis+unix://")

# Known platform environment variable indicators for TLS-terminating proxy platforms
_PROXY_PLATFORM_ENV_VARS = (
    "RAILWAY_ENVIRONMENT",   # Railway
    "RENDER",                # Render.com
    "FLY_APP_NAME",          # Fly.io
    "HEROKU_APP_NAME",       # Heroku
    "K_SERVICE",             # Google Cloud Run
)

_WEAK_KEY_PLACEHOLDERS = frozenset(
    {
        "secret",
        "changeme",
        "change-me",
        "change-me-in-production",
        "your-secret-key",
        "your_secret_key",
        "example",
        "insecure",
        "placeholder",
        "default",
        "password",
        "replace-me",
        "replace_me",
        "mysecretkey",
        "mysecret",
    }
)


def _validate_key_strength(name: str, v: str) -> str:
    if v.lower() in _WEAK_KEY_PLACEHOLDERS:
        raise ValueError(
            f"{name} appears to be a placeholder value; set a strong random secret"
        )
    if len(v) < 32:
        raise ValueError(f"{name} must be at least 32 characters; got {len(v)}")
    return v


def detected_proxy_platform() -> str | None:
    """Name of the first known TLS-terminating-proxy platform env var that is set, else None."""
    return next((v for v in _PROXY_PLATFORM_ENV_VARS if os.environ.get(v)), None)


class Settings(BaseSettings):
    """All settings loaded from environment variables or .env file."""

    # Trakt OAuth
    TRAKT_CLIENT_ID: str = ""
    TRAKT_CLIENT_SECRET: str = ""
    TRAKT_REDIRECT_URI: str = "http://localhost:8000/auth/callback"

    # SIMKL OAuth
    SIMKL_CLIENT_ID: str = ""
    SIMKL_CLIENT_SECRET: str = ""
    SIMKL_REDIRECT_URI: str = "http://localhost:8000/auth/simkl/callback"

    # Database (Supabase Postgres via connection string)
    DATABASE_URL: str

    # App secrets
    SECRET_KEY: str
    TOKEN_ENC_KEY: str = ""  # ≥32 chars; rotate independently of SECRET_KEY

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped or stripped == _LOCALHOST_DB_DEFAULT:
            raise ValueError(
                "DATABASE_URL must be set to a valid connection string; "
                "the hardcoded localhost default is not permitted"
            )
        return stripped

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        return _validate_key_strength("SECRET_KEY", v)

    @field_validator("TOKEN_ENC_KEY", mode="before")
    @classmethod
    def validate_token_enc_key(cls, v: str) -> str:
        if v == "":
            return v  # presence enforced by require_token_enc_key_with_oauth when OAuth is enabled
        return _validate_key_strength("TOKEN_ENC_KEY", v)

    @model_validator(mode="after")
    def require_token_enc_key_with_oauth(self) -> "Settings":
        """Reject startup when TOKEN_ENC_KEY is empty but an OAuth provider is configured."""
        oauth_enabled = bool(self.TRAKT_CLIENT_ID or self.SIMKL_CLIENT_ID)
        if oauth_enabled and not self.TOKEN_ENC_KEY:
            raise ValueError(
                "TOKEN_ENC_KEY must be set when TRAKT_CLIENT_ID or SIMKL_CLIENT_ID is configured"
            )
        return self

    BASE_URL: str = "http://localhost:8000"

    # TMDB for poster images
    TMDB_API_KEY: str = ""

    # LLM (OpenRouter / Requesty.ai)
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://router.requesty.ai/v1"
    LLM_MODEL: str = "google/gemini-3.1-flash-lite-preview"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def validate_cors_origins(cls, v: object) -> list[str]:
        if isinstance(v, str):
            entries = [o.strip() for o in v.split(",")]
        elif isinstance(v, list):
            entries = [str(o).strip() for o in v]
        else:
            raise ValueError("CORS_ORIGINS must be a comma-separated string or list")
        entries = [e for e in entries if e]  # drop empties
        if not entries:
            raise ValueError("CORS_ORIGINS must contain at least one origin")
        if "*" in entries:
            raise ValueError(
                "CORS_ORIGINS must not contain '*' when allow_credentials=True"
            )
        return entries

    # Data retention (days)
    DUEL_RETENTION_DAYS: int = 180
    SWIPE_RETENTION_DAYS: int = 180
    TOURNAMENT_LLM_RETENTION_DAYS: int = 180
    SUGGESTION_RETENTION_DAYS: int = 180
    FEEDBACK_RETENTION_DAYS: int = 365
    # Hour of day (UTC) at which the scheduled retention purge runs (0-23)
    PURGE_SCHEDULE_HOUR: Annotated[int, Field(ge=0, le=23)] = 2

    # Sentry
    SENTRY_DSN: str = ""

    # Rate-limit counter storage (slowapi). Empty = per-process in-memory (counters
    # reset on restart and are not shared across replicas). Set to a redis:// URI
    # so limits survive restarts and are shared by all instances (SEC-04, #572).
    RATE_LIMIT_STORAGE_URI: str = ""

    @field_validator("RATE_LIMIT_STORAGE_URI", mode="before")
    @classmethod
    def validate_rate_limit_storage_uri(cls, v: str) -> str:
        stripped = v.strip()
        if stripped and not stripped.startswith(_RATE_LIMIT_STORAGE_SCHEMES):
            raise ValueError(
                "RATE_LIMIT_STORAGE_URI must be empty or a redis://, rediss:// "
                "or redis+unix:// URI"
            )
        return stripped

    # Explicit override for cookie Secure flag.
    # Set SECURE_COOKIES=true when behind a TLS-terminating proxy with BASE_URL=http://.
    # Defaults to None (auto-detect from BASE_URL). On a detected hosted platform
    # with an http:// BASE_URL, leaving it unset refuses to start.
    SECURE_COOKIES: bool | None = None

    @model_validator(mode="after")
    def require_explicit_secure_cookies_on_proxy_platform(self) -> "Settings":
        """Refuse to start on a known TLS-terminating proxy platform unless the Secure flag is explicit.

        Behind such a proxy BASE_URL is usually http://, so the is_https fallback would
        silently issue session cookies without Secure (and without HSTS). Fail closed
        instead of warning (SEC-11, #579).
        """
        detected = detected_proxy_platform()
        if self.SECURE_COOKIES is None and not self.is_https and detected:
            raise ValueError(
                f"cookie_secure_unset: detected platform env var {detected!r} but "
                "SECURE_COOKIES is not explicitly configured and "
                f"BASE_URL={self.BASE_URL!r} does not use https://. Refusing to start: "
                "session cookies would be issued WITHOUT the Secure flag. Set "
                "SECURE_COOKIES=true (behind a TLS-terminating proxy) or "
                "SECURE_COOKIES=false (plain-http deployment, insecure) to proceed."
            )
        return self

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: object,
        env_settings: object,
        dotenv_settings: object,
        **kwargs: object,
    ) -> tuple[object, ...]:
        # pydantic-settings renamed secrets_settings → file_secret_settings in ≥2.4;
        # accept either via **kwargs for forward/backward compatibility.
        file_secret_settings = kwargs.get("file_secret_settings") or kwargs.get(
            "secrets_settings"
        )
        sources = [init_settings, _TolerantEnvSource(settings_cls), dotenv_settings]
        if file_secret_settings:
            sources.append(file_secret_settings)
        return tuple(sources)

    @property
    def is_https(self) -> bool:
        return self.BASE_URL.startswith("https://")

    @property
    def cookie_secure(self) -> bool:
        """Whether to set the Secure flag on session cookies.

        Explicit SECURE_COOKIES env var takes precedence; otherwise falls back
        to BASE_URL inference so existing deployments are unaffected.
        """
        return self.SECURE_COOKIES if self.SECURE_COOKIES is not None else self.is_https


@lru_cache
def get_settings() -> Settings:
    return Settings()
