"""Parity tests between the consent disclosure and what actually reaches the LLM (FD-054).

frontend/src/components/ConsentModal.jsx itemizes the data FilmDuel sends to the
AI gateway. These tests pin the service-side counterpart of every itemized claim,
so widening a payload — or changing a disclosed limit — fails here instead of
silently making the disclosure untrue.

The disclosed sizes live in requirements/fd-054-disclosed-limits.json, which
ConsentModal.test.jsx reads as well: moving a limit on one side alone leaves one
of the two suites red, whichever side moved.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.config import Settings
from backend.services.curator import curate_tournament
from backend.services.suggest import (
    CANDIDATE_LIMIT,
    NUM_PICKS,
    _build_taste_profile,
    _call_llm,
    _get_candidates,
    generate_suggestions,
)

DISCLOSED = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "requirements"
        / "fd-054-disclosed-limits.json"
    ).read_text()
)

# Canary values chosen so they cannot collide with years, ratings, trakt ids or
# counts that the prompt builders legitimately emit.
CANARY_TOP_ELO = 1337
CANARY_BOTTOM_ELO = 811
CANARY_MOVIE_ID = "11111111-2222-3333-4444-555555555555"
# The curation prompt legitimately carries the film id, so it needs its own value.
BRACKET_FILM_ID = "22222222-3333-4444-5555-666666666666"
CANARY_USER_ID = uuid.UUID("99999999-8888-7777-6666-555555555555")

_TASTE_PROFILE = {
    "top_10": [
        {
            "title": "Top Film",
            "year": 2001,
            "genres": ["Drama"],
            "elo": CANARY_TOP_ELO,
        }
    ],
    "bottom_5": [
        {
            "title": "Bottom Film",
            "year": 2002,
            "genres": ["Horror"],
            "elo": CANARY_BOTTOM_ELO,
        }
    ],
    "genre_affinities": {"Drama": CANARY_TOP_ELO},
    "total_ranked": 42,
}


def _candidate(index: int = 0) -> dict:
    return {
        "trakt_id": 7001 + index,
        "movie_id": CANARY_MOVIE_ID,
        "title": f"Candidate Film {index}",
        "year": 2003,
        "genres": ["Sci-Fi"],
        "community_rating": 8.5,
    }


class TestSuggestionPayloadMatchesDisclosure:
    """Modal: top 10 / bottom 5 (title, year, genres, preference tier), per-genre
    affinities, total ranked count, and a pool of up to 50 candidates
    (title, year, genres, community rating)."""

    @pytest.mark.asyncio
    async def test_prompt_carries_the_disclosed_fields_as_preference_tiers(self):
        llm = AsyncMock(return_value='{"picks": []}')
        with patch("backend.services.suggest.chat_completion", llm):
            await _call_llm(_TASTE_PROFILE, [_candidate()])

        prompt = llm.await_args.args[1]

        assert "Top Film (2001) [Drama] preference: highly preferred" in prompt
        assert "Bottom Film (2002) [Horror] preference: less preferred" in prompt
        assert "- Drama: highly preferred" in prompt
        assert "Total ranked films: 42" in prompt
        assert "Candidate Film 0 (2003) [Sci-Fi]" in prompt
        assert "rating=8.5" in prompt

    @pytest.mark.asyncio
    async def test_prompt_never_carries_raw_elo(self):
        llm = AsyncMock(return_value='{"picks": []}')
        with patch("backend.services.suggest.chat_completion", llm):
            await _call_llm(_TASTE_PROFILE, [_candidate()])

        prompt = llm.await_args.args[1]

        assert "preference: highly preferred" in prompt
        assert "preference: less preferred" in prompt
        assert str(CANARY_TOP_ELO) not in prompt
        assert str(CANARY_BOTTOM_ELO) not in prompt

    @pytest.mark.asyncio
    async def test_prompt_carries_no_catalog_row_id_beyond_trakt_id(self):
        """movie_id is in the candidate dict but is not a disclosed field."""
        llm = AsyncMock(return_value='{"picks": []}')
        with patch("backend.services.suggest.chat_completion", llm):
            await _call_llm(_TASTE_PROFILE, [_candidate()])

        prompt = llm.await_args.args[1]

        assert "trakt_id=7001" in prompt
        assert CANARY_MOVIE_ID not in prompt

    @pytest.mark.asyncio
    async def test_prompt_never_carries_the_account_identifier(self):
        llm = AsyncMock(return_value='{"picks": []}')
        with (
            patch(
                "backend.services.suggest._build_taste_profile",
                AsyncMock(return_value=_TASTE_PROFILE),
            ),
            patch(
                "backend.services.suggest._get_candidates",
                AsyncMock(return_value=[_candidate(i) for i in range(NUM_PICKS)]),
            ),
            patch("backend.services.suggest.chat_completion", llm),
        ):
            await generate_suggestions(CANARY_USER_ID, AsyncMock())

        system_prompt, user_prompt = llm.await_args.args[:2]

        assert "Candidate Film 0" in user_prompt
        assert str(CANARY_USER_ID) not in user_prompt
        assert str(CANARY_USER_ID) not in system_prompt

    def test_candidate_pool_cap_matches_the_disclosed_cap(self):
        assert CANDIDATE_LIMIT == DISCLOSED["candidate_pool_cap"]

    @pytest.mark.asyncio
    async def test_candidate_query_is_limited_to_the_capped_pool(self):
        db = AsyncMock()
        result = MagicMock()
        result.unique.return_value.scalars.return_value.all.return_value = []
        db.execute.return_value = result

        await _get_candidates(CANARY_USER_ID, db)

        stmt = db.execute.await_args.args[0]
        assert stmt._limit_clause.value == CANDIDATE_LIMIT


class TestTasteProfileSizeMatchesDisclosure:
    """Modal: "your top 10 and bottom 5 ranked films"."""

    @staticmethod
    def _ranked(count: int) -> list:
        films = []
        for i in range(count):
            um = MagicMock()
            um.elo = 1000 + i
            um.movie = MagicMock()
            um.movie.title = f"Film {i}"
            um.movie.year = 2000
            um.movie.genres = ["Drama"]
            films.append(um)
        return films

    @staticmethod
    def _result(items: list):
        result = MagicMock()
        result.unique.return_value.scalars.return_value.all.return_value = items
        return result

    @pytest.mark.asyncio
    async def test_top_slice_matches_the_disclosed_count(self):
        db = AsyncMock()
        db.execute.side_effect = [
            self._result(self._ranked(30)),
            self._result(self._ranked(5)),
        ]

        profile = await _build_taste_profile(CANARY_USER_ID, db)

        assert len(profile["top_10"]) == DISCLOSED["taste_profile_top_n"]

    @pytest.mark.asyncio
    async def test_bottom_query_matches_the_disclosed_count(self):
        db = AsyncMock()
        db.execute.side_effect = [
            self._result(self._ranked(30)),
            self._result(self._ranked(5)),
        ]

        await _build_taste_profile(CANARY_USER_ID, db)

        bottom_stmt = db.execute.await_args_list[1].args[0]
        assert bottom_stmt._limit_clause.value == DISCLOSED["taste_profile_bottom_n"]


class TestTournamentPayloadMatchesDisclosure:
    """Modal: "candidate films (title, year, genres, preference tier, duel count)
    plus any theme or filter you enter"."""

    _CANDIDATE = {
        "id": BRACKET_FILM_ID,
        "title": "Bracket Film",
        "year": 2004,
        "genres": ["Western"],
        "elo": CANARY_TOP_ELO,
        "battles": 23,
    }
    _RESPONSE = (
        '{"name": "n", "tagline": "t", "theme_description": "d",'
        ' "film_ids": ["f0", "f1", "f2", "f3", "f4", "f5", "f6", "f7"]}'
    )

    async def _capture(self, **kwargs) -> str:
        llm = AsyncMock(return_value=self._RESPONSE)
        with patch("backend.services.curator.chat_completion", llm):
            await curate_tournament(
                candidates=[self._CANDIDATE], bracket_size=8, **kwargs
            )
        return llm.await_args.args[1]

    @pytest.mark.asyncio
    async def test_prompt_carries_the_disclosed_fields_as_preference_tiers(self):
        prompt = await self._capture()

        assert '"Bracket Film" (2004)' in prompt
        assert "Genres: Western" in prompt
        assert "preference: highly preferred" in prompt
        assert "Battles: 23" in prompt

    @pytest.mark.asyncio
    async def test_prompt_never_carries_raw_elo(self):
        prompt = await self._capture()

        assert "preference: highly preferred" in prompt
        assert str(CANARY_TOP_ELO) not in prompt

    @pytest.mark.asyncio
    async def test_theme_and_filter_reach_the_prompt(self):
        prompt = await self._capture(filter_context="Genre: Horror", theme_hint="heists")

        assert "Active filter: Genre: Horror" in prompt
        assert "heists" in prompt


class TestGatewayMatchesDisclosure:
    def test_default_gateway_is_the_disclosed_vendor(self):
        assert "requesty.ai" in Settings.model_fields["LLM_BASE_URL"].default
