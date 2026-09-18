"""Tests for the TMDB client's credential transport (SEC-12, #580).

A v4 API Read Access Token must travel only in the Authorization header so it
never lands in request URLs; a v3 API Key can only go in the api_key query
parameter, so that path is pinned as the unchanged fallback.
"""

from __future__ import annotations

import functools
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.services.tmdb import (
    _client,
    fetch_poster_url,
    fetch_similar_films,
    fetch_tv_poster_url,
    is_read_access_token,
)

V4_TOKEN = "eyJhbGciOiJIUzI1NiJ9.eyJhdWQiOiJ0ZXN0In0.sig"
V3_KEY = "0123456789abcdef0123456789abcdef"


def _settings(token: str) -> MagicMock:
    return MagicMock(TMDB_API_KEY=token)


@contextmanager
def _tmdb(token: str, payload, status_code: int = 200):
    """Patch settings and route every AsyncClient through a MockTransport.

    Yields the list of real httpx.Request objects the code built, so tests can
    assert on the exact URL and headers that would have gone over the wire.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status_code, json=payload)

    transport = httpx.MockTransport(handler)
    with patch("backend.services.tmdb.get_settings", return_value=_settings(token)), \
         patch("httpx.AsyncClient", functools.partial(httpx.AsyncClient, transport=transport)):
        yield requests


class TestIsReadAccessToken:
    def test_jwt_shaped_value_is_token(self):
        assert is_read_access_token(V4_TOKEN) is True

    def test_v3_hex_key_is_not_token(self):
        assert is_read_access_token(V3_KEY) is False

    def test_empty_is_not_token(self):
        assert is_read_access_token("") is False


class TestClientAuth:
    def test_v4_token_goes_in_authorization_header(self):
        with patch("backend.services.tmdb.get_settings", return_value=_settings(V4_TOKEN)):
            client = _client()
        assert client.headers["Authorization"] == f"Bearer {V4_TOKEN}"
        assert "api_key" not in client.params

    def test_v3_key_goes_in_query_params(self):
        with patch("backend.services.tmdb.get_settings", return_value=_settings(V3_KEY)):
            client = _client()
        assert client.params["api_key"] == V3_KEY
        assert "Authorization" not in client.headers


class TestFetchPosterUrl:
    @pytest.mark.asyncio
    async def test_v4_token_never_in_url(self):
        with _tmdb(V4_TOKEN, {"poster_path": "/p.jpg"}) as requests:
            url = await fetch_poster_url(1)

        assert url == "https://image.tmdb.org/t/p/w500/p.jpg"
        (request,) = requests
        assert str(request.url) == "https://api.themoviedb.org/3/movie/1"
        assert request.headers["Authorization"] == f"Bearer {V4_TOKEN}"

    @pytest.mark.asyncio
    async def test_v3_key_still_sent_as_query_param(self):
        with _tmdb(V3_KEY, {"poster_path": "/p.jpg"}) as requests:
            url = await fetch_poster_url(1)

        assert url == "https://image.tmdb.org/t/p/w500/p.jpg"
        (request,) = requests
        assert request.url.params["api_key"] == V3_KEY
        assert "Authorization" not in request.headers

    @pytest.mark.asyncio
    async def test_empty_key_skips_request(self):
        with patch("backend.services.tmdb.get_settings", return_value=_settings("")), \
             patch("httpx.AsyncClient") as client_cls:
            assert await fetch_poster_url(1) is None
        client_cls.assert_not_called()


class TestFetchTvPosterUrl:
    @pytest.mark.asyncio
    async def test_v4_token_never_in_url(self):
        with _tmdb(V4_TOKEN, {"poster_path": "/tv.jpg"}) as requests:
            url = await fetch_tv_poster_url(7)

        assert url == "https://image.tmdb.org/t/p/w500/tv.jpg"
        (request,) = requests
        assert str(request.url) == "https://api.themoviedb.org/3/tv/7"
        assert request.headers["Authorization"] == f"Bearer {V4_TOKEN}"


class TestFetchSimilarFilms:
    _PAYLOAD = {
        "results": [
            {
                "id": 5,
                "title": "T",
                "release_date": "2020-01-01",
                "overview": "o",
                "genre_ids": [28, 999],
            }
        ]
    }

    @pytest.mark.asyncio
    async def test_v4_token_never_in_url(self):
        with _tmdb(V4_TOKEN, self._PAYLOAD) as requests:
            films = await fetch_similar_films(1)

        assert films == [
            {"tmdb_id": 5, "title": "T", "year": 2020, "overview": "o", "genres": ["action"]}
        ]
        (request,) = requests
        assert str(request.url) == "https://api.themoviedb.org/3/movie/1/recommendations"
        assert request.headers["Authorization"] == f"Bearer {V4_TOKEN}"

    @pytest.mark.asyncio
    async def test_v3_key_still_sent_as_query_param(self):
        with _tmdb(V3_KEY, self._PAYLOAD) as requests:
            await fetch_similar_films(1)

        (request,) = requests
        assert request.url.params["api_key"] == V3_KEY
        assert "Authorization" not in request.headers

    @pytest.mark.asyncio
    async def test_empty_key_skips_request(self):
        with patch("backend.services.tmdb.get_settings", return_value=_settings("")), \
             patch("httpx.AsyncClient") as client_cls:
            assert await fetch_similar_films(1) == []
        client_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_non_200_returns_empty(self):
        with _tmdb(V4_TOKEN, {}, status_code=404):
            assert await fetch_similar_films(1) == []
