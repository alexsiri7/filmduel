"""Tests for pair token encoding in routers/movies.py."""

from __future__ import annotations

import os
import uuid

import pytest


# Provide a test TOKEN_ENC_KEY so Fernet doesn't raise at import time
os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from backend.routers.movies import _decode_pair_token, _encode_pair_token


def test_pair_token_round_trips():
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    token = _encode_pair_token(id_a, id_b)
    result = _decode_pair_token(token)
    assert result == {id_a, id_b}


def test_pair_token_is_opaque():
    """Token must not contain the raw UUIDs in plaintext (base64 or otherwise)."""
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    token = _encode_pair_token(id_a, id_b)
    # Strip any base64 padding and check neither UUID appears in the token
    assert id_a not in token
    assert id_b not in token


def test_pair_token_invalid_returns_none():
    assert _decode_pair_token("not-a-valid-token") is None
    assert _decode_pair_token("") is None


def test_pair_token_tampered_returns_none():
    id_a = str(uuid.uuid4())
    id_b = str(uuid.uuid4())
    token = _encode_pair_token(id_a, id_b)
    tampered = token[:-4] + "XXXX"
    assert _decode_pair_token(tampered) is None
