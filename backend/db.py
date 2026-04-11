"""Supabase client initialization."""

from supabase import create_client, Client
from backend.config import get_settings


def get_supabase() -> Client:
    """Return a configured Supabase client."""
    settings = get_settings()
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)
