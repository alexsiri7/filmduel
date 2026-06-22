"""Application configuration via environment variables."""

from pydantic import field_validator
from pydantic_settings import BaseSettings
from functools import lru_cache

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
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

    # App secrets
    SECRET_KEY: str
    TOKEN_ENC_KEY: str = ""  # ≥32 chars; rotate independently of SECRET_KEY

    @field_validator("SECRET_KEY", mode="before")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        return _validate_key_strength("SECRET_KEY", v)

    @field_validator("TOKEN_ENC_KEY", mode="before")
    @classmethod
    def validate_token_enc_key(cls, v: str) -> str:
        if v == "":
            return v  # empty string is allowed; runtime check in token_crypto handles it
        return _validate_key_strength("TOKEN_ENC_KEY", v)

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
    # Hour of day (UTC) at which the scheduled retention purge runs (0-23)
    PURGE_SCHEDULE_HOUR: int = 2

    # Sentry
    SENTRY_DSN: str = ""

    # Explicit override for cookie Secure flag.
    # Set SECURE_COOKIES=true when behind a TLS-terminating proxy with BASE_URL=http://.
    # Defaults to None (auto-detect from BASE_URL).
    SECURE_COOKIES: bool | None = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def is_https(self) -> bool:
        return self.BASE_URL.startswith("https://")

    @property
    def cookie_secure(self) -> bool:
        """Whether to set the Secure flag on session cookies.

        Explicit SECURE_COOKIES env var takes precedence; otherwise falls back
        to BASE_URL inference so existing deployments are unaffected.
        """
        if self.SECURE_COOKIES is not None:
            return self.SECURE_COOKIES
        return self.is_https


@lru_cache
def get_settings() -> Settings:
    return Settings()
