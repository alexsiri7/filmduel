"""Tests for the post-deploy duel smoke script (#648)."""

from __future__ import annotations

import ast
import os
import sys
import uuid
from pathlib import Path

import jwt
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from backend.config import get_settings  # noqa: E402

get_settings.cache_clear()

from backend import duel_smoke  # noqa: E402
from backend.duel_smoke import SmokeFailure, mint_session_jwt, run  # noqa: E402
from backend.routers.auth import JWT_ALGORITHM, JWT_EXPIRY_HOURS  # noqa: E402
from backend.utils.cookies import COOKIE_NAME, cookie_name  # noqa: E402

PAIR = {
    "movie_a": {"id": "a-id"},
    "movie_b": {"id": "b-id"},
    "next_pair_token": "served-token",
}


class FakeRequest:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, token, body):
        self.calls.append((method, url, token, body))
        return self.responses.pop(0)


def test_minted_session_is_accepted_by_backend_decoder():
    settings = get_settings()
    user_id = str(uuid.uuid4())
    payload = jwt.decode(
        mint_session_jwt(user_id, settings.SECRET_KEY),
        settings.SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
        issuer="filmduel",
        audience="filmduel",
    )
    assert payload["sub"] == user_id
    assert isinstance(payload["orig_iat"], float)
    assert payload["exp"] - payload["iat"] <= JWT_EXPIRY_HOURS * 3600


def test_session_cookie_matches_backend_https_name():
    assert duel_smoke.SESSION_COOKIE == cookie_name(COOKIE_NAME, True)


def test_run_submits_the_served_pair():
    fake = FakeRequest((200, PAIR), (200, {"outcome": "a_wins"}))
    assert run("https://env.example/", "u", "k", request=fake) == {"outcome": "a_wins"}
    (get_method, get_url, *_), (post_method, post_url, _, body) = fake.calls
    assert (get_method, post_method) == ("GET", "POST")
    assert get_url.startswith("https://env.example/api/movies/pair")
    assert post_url == "https://env.example/api/duels"
    assert body == {
        "movie_a_id": "a-id",
        "movie_b_id": "b-id",
        "outcome": "a_wins",
        "mode": "discovery",
        "pair_token": "served-token",
    }


def test_rejected_duel_fails():
    fake = FakeRequest((200, PAIR), (400, {"detail": "Invalid pair token"}))
    with pytest.raises(SmokeFailure, match="400"):
        run("https://env.example", "u", "k", request=fake)


def test_no_pair_explains_seen_films():
    fake = FakeRequest((404, {"detail": "Not enough movies"}))
    with pytest.raises(SmokeFailure, match="seen films"):
        run("https://env.example", "u", "k", request=fake)


def test_missing_consent_explains_privacy_policy():
    fake = FakeRequest((200, PAIR), (403, {"detail": "consent required"}))
    with pytest.raises(SmokeFailure, match="privacy policy"):
        run("https://env.example", "u", "k", request=fake)


def test_main_reports_missing_env_by_name(monkeypatch, capsys):
    for name in ("SMOKE_BASE_URL", "SMOKE_USER_ID", "SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SMOKE_BASE_URL", "https://env.example")
    assert duel_smoke.main() == 2
    assert "SMOKE_USER_ID, SECRET_KEY" in capsys.readouterr().err


def test_script_imports_only_the_standard_library():
    tree = ast.parse(Path(duel_smoke.__file__).read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
    non_stdlib = {m for m in modules if m.split(".")[0] not in sys.stdlib_module_names}
    assert not non_stdlib
