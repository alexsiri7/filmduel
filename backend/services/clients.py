"""Factories for provider API clients, bound to the configured client id."""

from __future__ import annotations

from backend.config import Settings
from backend.services.simkl import SimklClient
from backend.services.trakt import TraktClient


def make_trakt_client(settings: Settings, **kw) -> TraktClient:
    return TraktClient(client_id=settings.TRAKT_CLIENT_ID, **kw)


def make_simkl_client(settings: Settings, **kw) -> SimklClient:
    return SimklClient(client_id=settings.SIMKL_CLIENT_ID, **kw)
