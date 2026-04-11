"""Trakt API client using async httpx."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from backend.config import get_settings

TRAKT_API_URL = "https://api.trakt.tv"


class TraktClient:
    """Async client for the Trakt.tv API."""

    def __init__(self, access_token: Optional[str] = None) -> None:
        settings = get_settings()
        self.client_id = settings.TRAKT_CLIENT_ID
        self.client_secret = settings.TRAKT_CLIENT_SECRET
        self.redirect_uri = settings.TRAKT_REDIRECT_URI
        self.access_token = access_token

    @property
    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": self.client_id,
        }
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange an OAuth authorization code for tokens."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{TRAKT_API_URL}/oauth/token",
                json={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def refresh_token(self, refresh_token: str) -> dict[str, Any]:
        """Exchange a refresh token for a new access token."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{TRAKT_API_URL}/oauth/token",
                json={
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "refresh_token",
                },
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user_profile(self) -> dict[str, Any]:
        """Fetch the authenticated user's profile."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{TRAKT_API_URL}/users/me",
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def get_popular_movies(self, page: int = 1, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch popular movies."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{TRAKT_API_URL}/movies/popular",
                headers=self._headers,
                params={"page": page, "limit": limit, "extended": "full"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_trending_movies(self, page: int = 1, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch trending movies."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{TRAKT_API_URL}/movies/trending",
                headers=self._headers,
                params={"page": page, "limit": limit, "extended": "full"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user_watched(self, username: str) -> list[dict[str, Any]]:
        """Fetch a user's watched movie history."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{TRAKT_API_URL}/users/{username}/watched/movies",
                headers=self._headers,
                params={"extended": "full"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user_ratings(self, username: str) -> list[dict[str, Any]]:
        """Fetch a user's movie ratings."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{TRAKT_API_URL}/users/{username}/ratings/movies",
                headers=self._headers,
                params={"extended": "full"},
            )
            resp.raise_for_status()
            return resp.json()

    async def rate_movie(self, trakt_id: int, rating: int) -> dict[str, Any]:
        """Submit a rating for a movie (1-10 scale)."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{TRAKT_API_URL}/sync/ratings",
                headers=self._headers,
                params={"extended": "full"},
                json={
                    "movies": [
                        {
                            "ids": {"trakt": trakt_id},
                            "rating": rating,
                        }
                    ]
                },
            )
            resp.raise_for_status()
            return resp.json()
