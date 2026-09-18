"""Unit tests for backend/services/data_export.py (GDPR Art. 15 / 20 export)."""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import sqlite

from backend.db_models import Base, User
from backend.services import data_export
from backend.services.data_export import build_export_payload, export_user_data

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

PROFILE_KEYS = {
    "id",
    "trakt_user_id",
    "trakt_username",
    "simkl_user_id",
    "simkl_username",
    "created_at",
    "last_seen_at",
    "sync_ratings_to_trakt",
    "sync_ratings_to_simkl",
    "use_ai_features",
    "is_admin",
    "privacy_policy_accepted",
    "privacy_policy_accepted_at",
    "privacy_policy_version",
}

MOVIE_REF_KEYS = {"id", "trakt_id", "imdb_id", "tmdb_id", "title", "year", "media_type"}


def _user(**overrides):
    fields = dict(
        id=uuid.uuid4(),
        trakt_user_id="trakt-123",
        trakt_username="alice",
        simkl_user_id="simkl-456",
        simkl_username="alice_s",
        created_at=NOW,
        last_seen_at=NOW,
        sync_ratings_to_trakt=True,
        sync_ratings_to_simkl=False,
        use_ai_features=True,
        is_admin=False,
        privacy_policy_accepted=True,
        privacy_policy_accepted_at=NOW,
        privacy_policy_version="2.1",
        trakt_access_token_enc="SECRET-trakt-access-enc",
        trakt_refresh_token_enc="SECRET-trakt-refresh-enc",
        simkl_access_token_enc="SECRET-simkl-access-enc",
        simkl_refresh_token_enc="SECRET-simkl-refresh-enc",
        trakt_access_token="SECRET-trakt-access",
        trakt_refresh_token="SECRET-trakt-refresh",
        simkl_access_token="SECRET-simkl-access",
        simkl_refresh_token="SECRET-simkl-refresh",
        trakt_token_expires_at=NOW,
        simkl_token_expires_at=NOW,
        tokens_invalid_before=NOW,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _movie(title="Heat", **overrides):
    fields = dict(
        id=uuid.uuid4(),
        trakt_id=42,
        imdb_id="tt0113277",
        tmdb_id=949,
        title=title,
        year=1995,
        media_type="movie",
        overview="should not be exported",
        poster_url="should not be exported",
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _empty_sections():
    return dict(
        user_movies=[],
        duels=[],
        tournaments=[],
        suggestions=[],
        swipe_results=[],
        feedback_reports=[],
        pool_expansions=[],
        truncated_sections=[],
    )


def _build(user=None, **sections):
    kwargs = _empty_sections()
    kwargs.update(sections)
    return build_export_payload(user or _user(), exported_at=NOW, **kwargs)


def _walk_keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _walk_keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v)


# ---------------------------------------------------------------------------
# Profile: credential boundary
# ---------------------------------------------------------------------------


def test_no_credential_material_in_payload():
    """Neither encrypted nor decrypted token values, nor token lifecycle keys, leak."""
    payload = _build()
    assert "SECRET-" not in json.dumps(payload)
    for key in _walk_keys(payload):
        assert "token" not in key, key
        assert "expires_at" not in key, key
        assert "invalid_before" not in key, key


def test_profile_is_exact_allow_list():
    payload = _build()
    assert set(payload["profile"].keys()) == PROFILE_KEYS


# Credential and token-lifecycle columns: the only User columns the export may skip.
DELIBERATELY_OMITTED_USER_COLUMNS = {
    "trakt_access_token",
    "trakt_refresh_token",
    "trakt_token_expires_at",
    "simkl_access_token",
    "simkl_refresh_token",
    "simkl_token_expires_at",
    "tokens_invalid_before",
}


def test_every_user_column_is_exported_or_deliberately_omitted():
    """A new personal column on User cannot silently go unexported."""
    columns = set(User.__table__.columns.keys())
    assert columns - PROFILE_KEYS == DELIBERATELY_OMITTED_USER_COLUMNS
    assert PROFILE_KEYS <= columns


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_payload_is_json_native():
    """UUIDs and tz-aware datetimes are already strings — json.dumps needs no default=."""
    user = _user()
    movie = _movie()
    um = SimpleNamespace(
        movie=movie, seen=True, elo=1500, seeded_elo=1400, battles=3,
        trakt_rating=8, last_dueled_at=NOW, updated_at=NOW,
    )
    payload = _build(user, user_movies=[um])
    json.dumps(payload)
    assert payload["profile"]["id"] == str(user.id)
    assert payload["profile"]["created_at"] == NOW.isoformat()
    assert payload["library"][0]["movie"]["id"] == str(movie.id)
    assert payload["library"][0]["updated_at"] == NOW.isoformat()
    assert payload["exported_at"] == NOW.isoformat()


def test_movie_identity_is_inlined_as_compact_ref():
    heat = _movie("Heat")
    ronin = _movie("Ronin")
    um = SimpleNamespace(
        movie=heat, seen=True, elo=1500, seeded_elo=None, battles=1,
        trakt_rating=None, last_dueled_at=None, updated_at=NOW,
    )
    duel = SimpleNamespace(
        id=uuid.uuid4(), created_at=NOW, mode="discovery", pair_type="close",
        winner_movie=heat, loser_movie=None,
        winner_elo_before=1500, winner_elo_after=1510,
        loser_elo_before=1500, loser_elo_after=1490,
    )
    match = SimpleNamespace(
        round=1, position=0, is_bye=False, played_at=NOW,
        movie_a=heat, movie_b=ronin, winner_movie=heat,
    )
    tournament = SimpleNamespace(
        id=uuid.uuid4(), name="90s Thrillers", filter_type="decade", filter_value="1990",
        media_type="movie", bracket_size=2, status="completed", created_at=NOW,
        completed_at=NOW, tagline=None, theme_description=None, is_ai_curated=False,
        llm_response={"raw": "x"}, champion_movie=heat, matches=[match],
    )
    suggestion = SimpleNamespace(
        id=uuid.uuid4(), movie=ronin, reason="because", generated_at=NOW,
        dismissed_at=None, added_to_watchlist_at=None,
    )
    swipe = SimpleNamespace(id=uuid.uuid4(), movie=ronin, seen=False, created_at=NOW)

    payload = _build(
        user_movies=[um], duels=[duel], tournaments=[tournament],
        suggestions=[suggestion], swipe_results=[swipe],
    )

    refs = {
        "library.movie": payload["library"][0]["movie"],
        "duels.winner": payload["duels"][0]["winner"],
        "tournaments.champion": payload["tournaments"][0]["champion"],
        "tournaments.matches.movie_a": payload["tournaments"][0]["matches"][0]["movie_a"],
        "tournaments.matches.movie_b": payload["tournaments"][0]["matches"][0]["movie_b"],
        "tournaments.matches.winner": payload["tournaments"][0]["matches"][0]["winner"],
        "suggestions.movie": payload["suggestions"][0]["movie"],
        "swipe_results.movie": payload["swipe_results"][0]["movie"],
    }
    for name, ref in refs.items():
        assert set(ref.keys()) == MOVIE_REF_KEYS, name
    assert refs["library.movie"]["title"] == "Heat"
    assert refs["tournaments.matches.movie_b"]["title"] == "Ronin"
    assert payload["duels"][0]["loser"] is None
    assert payload["tournaments"][0]["llm_response"] == {"raw": "x"}


def test_feedback_reports_expose_screenshot_presence_not_bytes():
    with_shot = SimpleNamespace(
        id=uuid.uuid4(), title="Bug", description="It broke", created_at=NOW,
        screenshot_data_enc="enc-bytes",
    )
    without = SimpleNamespace(
        id=uuid.uuid4(), title="Idea", description="Add dark mode", created_at=NOW,
        screenshot_data_enc=None,
    )
    payload = _build(feedback_reports=[with_shot, without])
    assert payload["feedback_reports"][0]["has_screenshot"] is True
    assert payload["feedback_reports"][1]["has_screenshot"] is False
    for entry in payload["feedback_reports"]:
        assert not any("screenshot_data" in k for k in entry)
    assert "enc-bytes" not in json.dumps(payload)


def test_tournament_matches_sorted_by_round_then_position():
    def m(r, p):
        return SimpleNamespace(
            round=r, position=p, is_bye=False, played_at=None,
            movie_a=None, movie_b=None, winner_movie=None,
        )

    tournament = SimpleNamespace(
        id=uuid.uuid4(), name="t", filter_type=None, filter_value=None, media_type="movie",
        bracket_size=4, status="active", created_at=NOW, completed_at=None, tagline=None,
        theme_description=None, is_ai_curated=False, llm_response=None,
        champion_movie=None, matches=[m(2, 0), m(1, 1), m(1, 0)],
    )
    payload = _build(tournaments=[tournament])
    order = [(x["round"], x["position"]) for x in payload["tournaments"][0]["matches"]]
    assert order == [(1, 0), (1, 1), (2, 0)]


# ---------------------------------------------------------------------------
# Coverage: every user-scoped table has a section
# ---------------------------------------------------------------------------


MODEL_TO_SECTION = {
    "UserMovie": "library",
    "Duel": "duels",
    "Tournament": "tournaments",
    "Suggestion": "suggestions",
    "SwipeResult": "swipe_results",
    "FeedbackReport": "feedback_reports",
    "PoolExpansion": "pool_expansions",
}


def test_every_user_scoped_table_is_exported():
    """Derived from the schema so a new user_id table cannot ship unexported (#581)."""
    user_scoped = {
        m.class_.__name__
        for m in Base.registry.mappers
        if "user_id" in m.class_.__table__.columns
    }
    assert user_scoped == set(MODEL_TO_SECTION), (
        "Add the new user-scoped model to the export and to MODEL_TO_SECTION"
    )
    payload = _build()
    assert set(MODEL_TO_SECTION.values()) <= set(payload)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _db_returning(rows_per_call):
    db = AsyncMock()
    results = []
    for rows in rows_per_call:
        r = MagicMock()
        r.unique.return_value.scalars.return_value.all.return_value = rows
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
    return db


@pytest.mark.asyncio
async def test_loader_statements_are_capped_and_user_scoped():
    db = _db_returning([[]] * 7)
    await export_user_data(db, _user())

    assert db.execute.call_count == 7
    for call in db.execute.call_args_list:
        compiled = str(
            call.args[0].compile(
                dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert re.search(r"\bLIMIT\s+10001\b", compiled, re.IGNORECASE), compiled
        assert "user_id" in compiled, compiled


@pytest.mark.asyncio
async def test_truncation_is_reported_not_silent(monkeypatch):
    monkeypatch.setattr(data_export, "EXPORT_ROW_CAP", 2)

    def um():
        return SimpleNamespace(
            movie=None, seen=True, elo=1500, seeded_elo=None, battles=0,
            trakt_rating=None, last_dueled_at=None, updated_at=NOW,
        )

    db = _db_returning([[um(), um(), um()]] + [[]] * 6)
    payload = await export_user_data(db, _user())
    assert len(payload["library"]) == 2
    assert payload["truncated_sections"] == ["library"]

    db = _db_returning([[um(), um()]] + [[]] * 6)
    payload = await export_user_data(db, _user())
    assert len(payload["library"]) == 2
    assert payload["truncated_sections"] == []
