"""Application configuration via environment variables."""

import ipaddress
import os
import ssl
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse

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

# Engine pool sizing for backend/db.py. Kept small: the database lives in
# schema `filmduel` of a Supabase project shared with other apps, so its pooler
# connection budget is shared too.
DB_POOL_SIZE = 3
DB_MAX_OVERFLOW = 2

_SUPABASE_ROOT_CA = Path(__file__).resolve().parent / "certs" / "supabase-root-2021-ca.crt"

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


# Hand-typed filler such as "a" * 32 or "abab…" uses one or two distinct
# characters. A random secret's count varies: 32 hex chars (token_hex(16))
# show fewer than 10 distinct digits about once in 10,000 draws, but fewer
# than 6 only about once in 3 trillion, so the floor is 6 (AUD-28, #710).
_MIN_DISTINCT_KEY_CHARS = 6


def _validate_key_strength(name: str, v: str) -> str:
    if v.lower() in _WEAK_KEY_PLACEHOLDERS:
        raise ValueError(
            f"{name} appears to be a placeholder value; set a strong random secret"
        )
    if len(v) < 32:
        raise ValueError(f"{name} must be at least 32 characters; got {len(v)}")
    distinct = len(set(v))
    if distinct < _MIN_DISTINCT_KEY_CHARS:
        raise ValueError(
            f"{name} uses only {distinct} distinct characters (minimum "
            f"{_MIN_DISTINCT_KEY_CHARS}); set a strong random secret, e.g. "
            "python -c 'import secrets; print(secrets.token_hex(32))'"
        )
    return v


def _is_loopback_origin(origin: str) -> bool:
    """True when the origin's host is localhost, *.localhost or a loopback/unspecified IP."""
    host = (urlparse(origin).hostname or "").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_unspecified


_PRIVATE_HOST_SUFFIXES = (".localhost", ".internal", ".local", ".home.arpa")


def is_cleartext_public_redis_uri(uri: str) -> bool:
    """True when uri is plain redis:// (no TLS) to a host not recognisably private (SEC-26, #798).

    Judged from the URI text only (no DNS): loopback, private and link-local IP
    literals, single-label names, localhost and the .internal/.local/.home.arpa
    suffixes (e.g. Railway's *.railway.internal) count as private.
    """
    parsed = urlparse(uri)
    if parsed.scheme != "redis":
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    # IP literals first: an IPv6 literal has no dot and would pass as a single-label name.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        private_name = (
            not host
            or host == "localhost"
            or "." not in host
            or host.endswith(_PRIVATE_HOST_SUFFIXES)
        )
        return not private_name
    return not (ip.is_private or ip.is_loopback or ip.is_link_local)


def _is_bare_origin(origin: str) -> bool:
    """True when the entry is exactly scheme://host[:port], the only shape a browser's Origin takes."""
    parsed = urlparse(origin)
    return (
        bool(parsed.netloc)
        and "@" not in parsed.netloc
        and origin == f"{parsed.scheme}://{parsed.netloc}"
    )


def _redact_userinfo(entry: str) -> str:
    """Mask everything between the scheme and the last '@', so a credential never reaches startup logs."""
    if "@" not in entry:
        return entry
    head, _, host = entry.rpartition("@")
    scheme, sep, _ = head.partition("://")
    return f"{scheme}{sep}***@{host}" if sep else f"***@{host}"


def detected_proxy_platform() -> str | None:
    """Name of the first known TLS-terminating-proxy platform env var that is set, else None."""
    return next((v for v in _PROXY_PLATFORM_ENV_VARS if os.environ.get(v)), None)


def database_connect_args() -> dict[str, object]:
    """asyncpg connect_args shared by the app engine and Alembic.

    On a detected hosted platform the connection must use TLS and verify the
    server against Supabase's root CA, which closes both the silent cleartext
    fallback and impersonation (AUD-04, #686). Off-platform it keeps asyncpg's
    default so a local Postgres without TLS still works.
    """
    # Supabase pooler (PgBouncer transaction mode) doesn't support prepared statements
    args: dict[str, object] = {"statement_cache_size": 0, "prepared_statement_cache_size": 0}
    if detected_proxy_platform():
        ctx = ssl.create_default_context(cafile=_SUPABASE_ROOT_CA)
        # Supabase's intermediate CA has no keyUsage extension, which the
        # VERIFY_X509_STRICT default (Python 3.13+) rejects.
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        args["ssl"] = ctx
    return args


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
    # Post-deploy duel smoke test (#648, #794): sessions signed with this key are
    # accepted for SMOKE_USER_ID only, so CI never holds SECRET_KEY.
    SMOKE_SESSION_KEY: str = ""
    SMOKE_USER_ID: str = ""

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

    @field_validator("SMOKE_SESSION_KEY", mode="before")
    @classmethod
    def validate_smoke_session_key(cls, v: str) -> str:
        if v == "":
            return v  # optional; pairing enforced by require_smoke_settings_together
        return _validate_key_strength("SMOKE_SESSION_KEY", v)

    @field_validator("SMOKE_USER_ID", mode="before")
    @classmethod
    def validate_smoke_user_id(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            return stripped
        try:
            return str(uuid.UUID(stripped))
        except ValueError:
            raise ValueError("SMOKE_USER_ID must be a UUID") from None

    @model_validator(mode="after")
    def require_smoke_settings_together(self) -> "Settings":
        """A smoke key needs the one user it may sign for, and must not be SECRET_KEY."""
        if bool(self.SMOKE_SESSION_KEY) != bool(self.SMOKE_USER_ID):
            raise ValueError("SMOKE_SESSION_KEY and SMOKE_USER_ID must be set together")
        if self.SMOKE_SESSION_KEY and self.SMOKE_SESSION_KEY == self.SECRET_KEY:
            raise ValueError("SMOKE_SESSION_KEY must differ from SECRET_KEY")
        return self

    BASE_URL: str = "http://localhost:8000"

    # TMDB for poster images
    TMDB_API_KEY: str = ""

    # LLM (OpenRouter / Requesty.ai)
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://router.requesty.ai/v1"
    LLM_MODEL: str = "google/gemini-3.1-flash-lite-preview"
    # Hard ceiling on one chat completion. Each in-flight call pins a pooled DB
    # connection in the calling request (AUD-01), so this must stay well below
    # the engine's pool_timeout (30 s) multiplied by the pool size.
    LLM_TIMEOUT_SECONDS: Annotated[float, Field(gt=0, le=120)] = 30.0
    # Process-wide cap on concurrent LLM calls; see llm_slots_below_pool_capacity.
    LLM_MAX_CONCURRENT: Annotated[int, Field(ge=1)] = 2

    @model_validator(mode="after")
    def llm_slots_below_pool_capacity(self) -> "Settings":
        """Each in-flight LLM call pins a pooled DB connection (AUD-01), so the
        cap must leave at least one connection free for everything else."""
        pool_capacity = DB_POOL_SIZE + DB_MAX_OVERFLOW
        if self.LLM_MAX_CONCURRENT >= pool_capacity:
            raise ValueError(
                f"LLM_MAX_CONCURRENT must be below the DB pool capacity ({pool_capacity})"
            )
        return self

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
        malformed = [_redact_userinfo(e) for e in entries if not _is_bare_origin(e)]
        if malformed:
            raise ValueError(
                f"CORS_ORIGINS entries must be scheme://host[:port] with no userinfo, "
                f"trailing slash, path, query or fragment; got {malformed!r}"
            )
        return entries

    @model_validator(mode="after")
    def reject_loopback_cors_origins_on_proxy_platform(self) -> "Settings":
        """Refuse to start on a hosted platform while CORS_ORIGINS names a loopback origin.

        CORS_ORIGINS defaults to the localhost dev servers, and the CSRF origin
        check trusts every entry. A deployment that never set CORS_ORIGINS would
        therefore accept state-changing requests from any page served on the
        visitor's own localhost. No hosted deployment has a legitimate loopback
        origin, so fail closed instead (AUD-23, #705).
        """
        detected = detected_proxy_platform()
        if not detected:
            return self
        loopback = [o for o in self.CORS_ORIGINS if _is_loopback_origin(o)]
        if loopback:
            raise ValueError(
                f"cors_origins_loopback: detected platform env var {detected!r} but "
                f"CORS_ORIGINS contains loopback origin(s) {loopback!r} (the localhost "
                "default applies when CORS_ORIGINS is unset). Refusing to start: the "
                "CSRF origin check would trust them. Set CORS_ORIGINS to the public "
                "origin(s) of this deployment, e.g. https://filmduel.example.com."
            )
        return self

    @model_validator(mode="after")
    def require_https_cors_origins_on_proxy_platform(self) -> "Settings":
        """Refuse to start on a hosted platform while CORS_ORIGINS names a non-https origin.

        Hosted platforms terminate TLS, so a plain-http origin there is a
        misconfiguration that the CSRF origin check would still trust (SEC-25, #797).
        """
        detected = detected_proxy_platform()
        if not detected:
            return self
        insecure = [o for o in self.CORS_ORIGINS if urlparse(o).scheme != "https"]
        if insecure:
            raise ValueError(
                f"cors_origins_insecure: detected platform env var {detected!r} but "
                f"CORS_ORIGINS contains non-https origin(s) {insecure!r}. Refusing to "
                "start: the CSRF origin check would trust them. Use the https:// "
                "origin(s) of this deployment."
            )
        return self

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
    # Plain redis:// to a non-private host logs a startup warning; prefer rediss://
    # or a private-network host (SEC-26, #798).
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

    # hide_input_in_errors: a rejected SECRET_KEY / TOKEN_ENC_KEY / SMOKE_SESSION_KEY /
    # DATABASE_URL must not be echoed into startup logs via ValidationError's input_value.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "hide_input_in_errors": True,
    }

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
