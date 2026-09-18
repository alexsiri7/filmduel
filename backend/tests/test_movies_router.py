"""Tests for pair token encoding in routers/movies.py."""

from __future__ import annotations

import os
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

# Provide a test TOKEN_ENC_KEY so Fernet doesn't raise at import time.
# Must set env vars AND clear the settings cache before importing backend modules
# because get_settings() is lru_cache'd and may already be populated (with
# TOKEN_ENC_KEY="") by earlier test modules that import backend.
os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from backend.config import get_settings  # noqa: E402

get_settings.cache_clear()

from backend.services.token_crypto import _fernet, encrypt_token  # noqa: E402

_fernet.cache_clear()

from backend.main import app  # noqa: E402
from backend.db import get_db  # noqa: E402
from backend.routers.auth import get_current_user  # noqa: E402
from backend.utils.tokens import (  # noqa: E402
    PAIR_TOKEN_TTL_SECONDS,
    decode_pair_token,
    encode_pair_token,
)


def test_pair_token_round_trips():
    user_id = str(uuid.uuid4())
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    token = encode_pair_token(id_a, id_b, user_id=user_id)
    result = decode_pair_token(token, user_id=user_id)
    assert result == {id_a, id_b}


def test_pair_token_is_opaque():
    """Token must not contain the raw UUIDs in plaintext (base64 or otherwise)."""
    user_id = str(uuid.uuid4())
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    token = encode_pair_token(id_a, id_b, user_id=user_id)
    # Check no UUID appears in the token
    assert user_id not in token
    assert id_a not in token
    assert id_b not in token


def test_pair_token_invalid_returns_none():
    user_id = str(uuid.uuid4())
    assert decode_pair_token("not-a-valid-token", user_id=user_id) is None
    assert decode_pair_token("", user_id=user_id) is None


def test_pair_token_tampered_returns_none():
    user_id = str(uuid.uuid4())
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    token = encode_pair_token(id_a, id_b, user_id=user_id)
    tampered = token[:-4] + "XXXX"
    assert decode_pair_token(tampered, user_id=user_id) is None


def test_pair_token_rejects_other_user():
    """A token minted for one user must not validate for another."""
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    token = encode_pair_token(id_a, id_b, user_id=str(uuid.uuid4()))
    assert decode_pair_token(token, user_id=str(uuid.uuid4())) is None


def test_pair_token_rejects_legacy_two_field_format():
    """Pre-user-binding tokens (movie IDs only) are rejected for every user."""
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    legacy = encrypt_token(f"{id_a},{id_b}")
    assert decode_pair_token(legacy, user_id=str(uuid.uuid4())) is None


def test_pair_token_expires_after_ttl():
    user_id = str(uuid.uuid4())
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    plaintext = f"{user_id},{id_a},{id_b}".encode()
    now = int(time.time())

    fresh = _fernet().encrypt_at_time(plaintext, now - PAIR_TOKEN_TTL_SECONDS + 60)
    assert decode_pair_token(fresh.decode(), user_id=user_id) == {id_a, id_b}

    stale = _fernet().encrypt_at_time(plaintext, now - PAIR_TOKEN_TTL_SECONDS - 60)
    assert decode_pair_token(stale.decode(), user_id=user_id) is None


def test_pair_token_ttl_none_accepts_aged_token():
    """The anti-repeat hint on GET /pair must survive token age; only the
    default (submit) path expires."""
    user_id = str(uuid.uuid4())
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    plaintext = f"{user_id},{id_a},{id_b}".encode()
    aged = _fernet().encrypt_at_time(
        plaintext, int(time.time()) - PAIR_TOKEN_TTL_SECONDS - 60
    ).decode()

    assert decode_pair_token(aged, user_id=user_id) is None
    assert decode_pair_token(aged, user_id=user_id, ttl=None) == {id_a, id_b}
    assert decode_pair_token(aged, user_id=str(uuid.uuid4()), ttl=None) is None


# ---------------------------------------------------------------------------
# GET /api/movies/pair
# ---------------------------------------------------------------------------


def _make_user_movie(movie_id: str) -> MagicMock:
    movie = MagicMock()
    movie.id = movie_id
    movie.trakt_id = 1
    movie.tmdb_id = None
    movie.imdb_id = None
    movie.title = f"Film {movie_id[:8]}"
    movie.year = 2000
    movie.poster_url = None
    movie.overview = None
    movie.genres = None
    movie.media_type = "movie"

    um = MagicMock()
    um.movie = movie
    um.movie_id = movie_id
    um.seen = True
    um.elo = None
    um.battles = 0
    return um


class TestGetMoviePair:
    def setup_method(self):
        self.user = MagicMock()
        self.user.id = uuid.uuid4()
        self.id_a = str(uuid.uuid4())
        self.id_b = str(uuid.uuid4())
        self.pair = (_make_user_movie(self.id_a), _make_user_movie(self.id_b))
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def _get_pair(self, **params):
        with patch(
            "backend.routers.movies.select_pair", new_callable=AsyncMock
        ) as mock_select_pair:
            mock_select_pair.return_value = self.pair
            with TestClient(app) as client:
                resp = client.get("/api/movies/pair", params=params)
        assert resp.status_code == 200, resp.text
        return resp.json(), mock_select_pair

    def test_minted_token_is_bound_to_requesting_user(self):
        body, _ = self._get_pair()
        token = body["next_pair_token"]
        served = {body["movie_a"]["id"], body["movie_b"]["id"]}

        assert served == {self.id_a, self.id_b}
        assert decode_pair_token(token, user_id=str(self.user.id)) == served
        assert decode_pair_token(token, user_id=str(uuid.uuid4())) is None

    def test_last_pair_token_excludes_previous_pair(self):
        body, _ = self._get_pair()
        _, mock_select_pair = self._get_pair(last_pair_token=body["next_pair_token"])
        assert mock_select_pair.call_args.args[2] == {self.id_a, self.id_b}

    def test_aged_last_pair_token_still_excludes_previous_pair(self):
        """FD-024: a client that deliberated past the submit TTL must still not
        be re-served the pair it is looking at."""
        plaintext = f"{self.user.id},{self.id_a},{self.id_b}".encode()
        aged = _fernet().encrypt_at_time(
            plaintext, int(time.time()) - PAIR_TOKEN_TTL_SECONDS - 60
        ).decode()

        _, mock_select_pair = self._get_pair(last_pair_token=aged)
        assert mock_select_pair.call_args.args[2] == {self.id_a, self.id_b}
