"""Tests for pair token encoding in routers/movies.py."""

from __future__ import annotations

import os
import time
import uuid

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
