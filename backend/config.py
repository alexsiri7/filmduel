"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """All settings loaded from environment variables or .env file."""

    # Trakt OAuth
    TRAKT_CLIENT_ID: str = ""
    TRAKT_CLIENT_SECRET: str = ""
    TRAKT_REDIRECT_URI: str = "http://localhost:8000/api/auth/callback"

    # Database (Supabase Postgres via connection string)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/postgres"

    # App secrets
    SECRET_KEY: str
    BASE_URL: str = "http://localhost:8000"

    # TMDB for poster images
    TMDB_API_KEY: str = ""

    # Anthropic (AI-curated tournaments)
    ANTHROPIC_API_KEY: str = ""

    # Sentry
    SENTRY_DSN: str = ""

    # ELO defaults
    ELO_K_FACTOR: int = 32
    ELO_DEFAULT_RATING: int = 1000

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
