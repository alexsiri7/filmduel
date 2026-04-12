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

    async def get_popular(self, limit: int = 100) -> list[dict]:
        """Fetch popular movies."""
        async with self._client() as client:
            resp = await client.get(
                "/movies/popular",
                params={"limit": limit, "extended": "full"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_trending(self, limit: int = 100) -> list[dict]:
        """Fetch trending movies.

        Trending returns [{watchers, movie}, ...] — this extracts the movie
        dicts.
        """
        async with self._client() as client:
            resp = await client.get(
                "/movies/trending",
                params={"limit": limit, "extended": "full"},
            )
            resp.raise_for_status()
            return [item["movie"] for item in resp.json()]

    async def get_user_watched(self, username: str) -> list[dict]:
        """Fetch a user's watched movies.

        Returns [{plays, last_watched_at, movie}, ...] — this extracts the
        movie dicts.
        """
        async with self._client() as client:
            resp = await client.get(
                f"/users/{username}/watched/movies",
                params={"extended": "full"},
            )
            resp.raise_for_status()
            return [item["movie"] for item in resp.json()]

    async def get_user_ratings(self, username: str) -> list[dict]:
        """Fetch a user's movie ratings.

        Returns [{rating, movie}, ...] — keeps rating + movie.ids.trakt.
        """
        async with self._client() as client:
            resp = await client.get(
                f"/users/{username}/ratings/movies",
            )
            resp.raise_for_status()
            return [
                {"rating": item["rating"], "trakt_id": item["movie"]["ids"]["trakt"]}
                for item in resp.json()
            ]

    async def rate_movie(self, trakt_id: int, rating: int) -> None:
        """Submit a rating for a movie (1-10 scale)."""
        async with self._client() as client:
            resp = await client.post(
                "/sync/ratings",
                json={
                    "movies": [
                        {
                            "rating": rating,
                            "ids": {"trakt": trakt_id},
                        }
                    ]
                },
            )
            resp.raise_for_status()

    async def add_to_watchlist(self, trakt_id: int) -> None:
        """Add a movie to the user's Trakt watchlist."""
        async with self._client() as client:
            resp = await client.post(
                "/sync/watchlist",
                json={
                    "movies": [{"ids": {"trakt": trakt_id}}]
                },
            )
            resp.raise_for_status()
