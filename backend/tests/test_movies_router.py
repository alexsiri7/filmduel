"""Tests for pair token encoding and movie pair endpoint in routers/movies.py."""

from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

# Provide a test TOKEN_ENC_KEY so Fernet doesn't raise at import time.
# Must set env vars AND clear the settings cache before importing backend modules
# because get_settings() is lru_cache'd and may already be populated (with
# TOKEN_ENC_KEY="") by earlier test modules that import backend.
os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from backend.config import get_settings  # noqa: E402

get_settings.cache_clear()

from backend.services.token_crypto import _fernet  # noqa: E402

_fernet.cache_clear()

from fastapi.testclient import TestClient  # noqa: E402

from backend.db import get_db  # noqa: E402
from backend.main import app  # noqa: E402
from backend.routers.auth import get_current_user  # noqa: E402
from backend.utils.tokens import decode_pair_token, encode_pair_token  # noqa: E402


def test_pair_token_round_trips():
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    token = encode_pair_token(id_a, id_b)
    result = decode_pair_token(token)
    assert result == {id_a, id_b}


def test_pair_token_is_opaque():
    """Token must not contain the raw UUIDs in plaintext (base64 or otherwise)."""
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    token = encode_pair_token(id_a, id_b)
    # Strip any base64 padding and check neither UUID appears in the token
    assert id_a not in token
    assert id_b not in token


def test_pair_token_invalid_returns_none():
    assert decode_pair_token("not-a-valid-token") is None
    assert decode_pair_token("") is None


def test_pair_token_tampered_returns_none():
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    token = encode_pair_token(id_a, id_b)
    tampered = token[:-4] + "XXXX"
    assert decode_pair_token(tampered) is None


class TestGetMoviePairValueError:
    """Verify that ValueError from select_pair returns generic 404 — not str(e)."""

    def setup_method(self):
        user = MagicMock()
        user.id = uuid.uuid4()
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_db] = lambda: AsyncMock()

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_select_pair_value_error_returns_generic_404(self):
        """ValueError from select_pair must return 404 with generic detail — not str(e)."""
        with patch(
            "backend.routers.movies.select_pair", new_callable=AsyncMock
        ) as mock_sp:
            mock_sp.side_effect = ValueError(
                "Not enough seen films for media_type=movie: internal detail"
            )
            client = TestClient(app)
            response = client.get("/api/movies/pair")

        assert response.status_code == 404
        assert response.json()["detail"] == "No eligible pair found"
        assert "internal" not in response.json()["detail"]
        assert "seen films" not in response.json()["detail"]
