"""SIMKL API client using async httpx."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class SimklClient:
    """Async client for the SIMKL API."""

    BASE_URL = "https://api.simkl.com"

    def __init__(self, client_id: str, access_token: str | None = None) -> None:
        self._headers: dict[str, str] = {
            "Content-Type": "application/json",
            "simkl-api-key": client_id,
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
        self, code: str, client_secret: str, redirect_uri: str, code_verifier: str | None = None
    ) -> dict:
        """Exchange an OAuth authorization code for tokens.

        Pass ``code_verifier`` to include PKCE proof in the token request (RFC 7636).
        Omit it for non-PKCE flows.
        """
        body: dict = {
            "code": code,
            "client_id": self._client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }
        if code_verifier is not None:
            body["code_verifier"] = code_verifier
        async with self._client() as client:
            resp = await client.post("/oauth/token", json=body)
            resp.raise_for_status()
            return resp.json()

    async def get_profile(self) -> dict:
        """Fetch authenticated user's settings/profile."""
        async with self._client() as client:
            resp = await client.get("/users/settings")
            resp.raise_for_status()
            return resp.json()

    async def get_popular(
        self, limit: int = 100, media_type: str = "movie"
    ) -> list[dict]:
        """Fetch popular movies or shows."""
        async with self._client() as client:
            resp = await client.get(
                f"/{media_type}s/popular",
                params={"limit": limit, "extended": "full"},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_trending(
        self, limit: int = 100, media_type: str = "movie"
    ) -> list[dict]:
        """Fetch trending movies or shows."""
        async with self._client() as client:
            resp = await client.get(
                f"/{media_type}s/trending",
                params={"limit": limit},
            )
            resp.raise_for_status()
            return resp.json()

    async def get_user_watched(self, media_type: str = "movie") -> list[dict]:
        """Fetch authenticated user's watched list."""
        async with self._client() as client:
            resp = await client.get(f"/sync/all-items/{media_type}s/watched")
            resp.raise_for_status()
            data = resp.json()
            # Unwrap wrapper objects — each item is {"last_watched_at": ..., "movie": {...}}
            return [
                entry[media_type]
                for entry in data.get(f"{media_type}s", [])
                if media_type in entry
            ]

    async def get_user_ratings(self, media_type: str = "movie") -> list[dict]:
        """Fetch user ratings. Returns [{rating, simkl_id}, ...]."""
        async with self._client() as client:
            resp = await client.get(f"/sync/ratings/{media_type}s")
            resp.raise_for_status()
            return [
                {
                    "rating": item["rating"],
                    "simkl_id": item[media_type]["ids"]["simkl"],
                }
                for item in resp.json()
            ]

    async def rate(
        self, simkl_id: int, rating: int, media_type: str = "movie"
    ) -> None:
        """Submit a rating (1-10 scale)."""
        async with self._client() as client:
            resp = await client.post(
                "/sync/ratings",
                json={
                    f"{media_type}s": [
                        {"rating": rating, "ids": {"simkl": simkl_id}}
                    ]
                },
            )
            resp.raise_for_status()

    async def revoke_token(self, token: str, *, client_secret: str) -> None:
        """Revoke token. Best-effort — does not raise on failure."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    f"{self.BASE_URL}/oauth/revoke-token",
                    headers={"simkl-api-key": self._client_id},
                    json={
                        "token": token,
                        "client_id": self._client_id,
                        "client_secret": client_secret,
                    },
                )
        except Exception:
            logger.warning("SIMKL token revoke failed", exc_info=True)
