"""Trakt API client using async httpx."""

from __future__ import annotations

import httpx


class TraktClient:
    """Async client for the Trakt.tv API."""

    BASE_URL = "https://api.trakt.tv"

    def __init__(self, client_id: str, access_token: str | None = None) -> None:
        self._headers: dict[str, str] = {
            "Content-Type": "application/json",
            "trakt-api-version": "2",
            "trakt-api-key": client_id,
        }
        self._client_id = client_id
        if access_token:
            self._headers["Authorization"] = f"Bearer {access_token}"

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers=self._headers,
        )

    async def exchange_code(
        self, code: str, client_secret: str, redirect_uri: str
    ) -> dict:
        """Exchange an OAuth authorization code for tokens."""
        async with self._client() as client:
            resp = await client.post(
                "/oauth/token",
                json={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def refresh_token(
        self, refresh_token: str, client_secret: str, redirect_uri: str
    ) -> dict:
        """Exchange a refresh token for a new access token."""
        async with self._client() as client:
            resp = await client.post(
                "/oauth/token",
                json={
                    "refresh_token": refresh_token,
                    "client_id": self._client_id,
                    "client_secret": client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            return resp.json()

    async def get_profile(self) -> dict:
        """Fetch the authenticated user's profile."""
        async with self._client() as client:
            resp = await client.get("/users/me")
            resp.raise_for_status()
            return resp.json()

    async def get_popular(self, limit: int = 100, media_type: str = "movie") -> list[dict]:
        """Fetch popular movies or shows."""
        async with self._client() as client:
            resp = await client.get(
                f"/{media_type}s/popular",
                params={"limit": limit, "extended": "full"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_trending(self, limit: int = 100, media_type: str = "movie") -> list[dict]:
        """Fetch trending movies or shows.

        Trending returns [{watchers, movie/show}, ...] — this extracts the
        inner dicts.
        """
        async with self._client() as client:
            resp = await client.get(
                f"/{media_type}s/trending",
                params={"limit": limit, "extended": "full"},
            )
            resp.raise_for_status()
            return [item[media_type] for item in resp.json()]

    async def get_user_watched(self, username: str, media_type: str = "movie") -> list[dict]:
        """Fetch a user's watched movies or shows.

        Returns [{plays, last_watched_at, movie/show}, ...] — this extracts
        the inner dicts.
        """
        async with self._client() as client:
            resp = await client.get(
                f"/users/{username}/watched/{media_type}s",
                params={"extended": "full"},
            )
            resp.raise_for_status()
            return [item[media_type] for item in resp.json()]

    async def get_user_ratings(self, username: str, media_type: str = "movie") -> list[dict]:
        """Fetch a user's movie or show ratings.

        Returns [{rating, trakt_id}, ...].
        """
        async with self._client() as client:
            resp = await client.get(
                f"/users/{username}/ratings/{media_type}s",
            )
            resp.raise_for_status()
            return [
                {"rating": item["rating"], "trakt_id": item[media_type]["ids"]["trakt"]}
                for item in resp.json()
            ]

    async def rate(self, trakt_id: int, rating: int, media_type: str = "movie") -> None:
        """Submit a rating for a movie or show (1-10 scale)."""
        async with self._client() as client:
            resp = await client.post(
                "/sync/ratings",
                json={
                    f"{media_type}s": [
                        {
                            "rating": rating,
                            "ids": {"trakt": trakt_id},
                        }
                    ]
                },
            )
            resp.raise_for_status()

    async def get_recommendations(self, limit: int = 100, media_type: str = "movie") -> list[dict]:
        """Get personalized recommendations for the authenticated user."""
        async with self._client() as client:
            resp = await client.get(
                f"/recommendations/{media_type}s",
                params={"limit": limit, "extended": "full", "ignore_collected": "true"},
            )
            resp.raise_for_status()
            return resp.json()

    async def add_to_watchlist(self, trakt_id: int, media_type: str = "movie") -> None:
        """Add a movie or show to the user's Trakt watchlist."""
        async with self._client() as client:
            resp = await client.post(
                "/sync/watchlist",
                json={
                    f"{media_type}s": [{"ids": {"trakt": trakt_id}}]
                },
            )
            resp.raise_for_status()
