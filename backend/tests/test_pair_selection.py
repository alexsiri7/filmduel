"""Tests for pair selection algorithm in routers/movies.py."""

import random
import unittest.mock
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.services.pair_selection import (
    BAND_ORDER,
    _band_filtered_candidates,
    _film_band,
    _pick_bootstrap_pair,
    _pick_challenger,
    _weighted_sample,
    bands_adjacent,
    community_rating_to_band,
    elo_to_band,
)


# ---------------------------------------------------------------------------
# Helpers to create mock UserMovie objects
# ---------------------------------------------------------------------------


def _make_user_movie(
    elo=None, battles=0, community_rating=None, movie_id=None, seen=True
):
    """Create a mock UserMovie with a nested mock Movie."""
    um = MagicMock()
    um.elo = elo
    um.battles = battles
    um.seen = seen
    um.movie_id = movie_id or uuid.uuid4()

    movie = MagicMock()
    movie.community_rating = community_rating
    um.movie = movie
    return um


# ---------------------------------------------------------------------------
# elo_to_band
# ---------------------------------------------------------------------------


class TestEloToBand:
    def test_none_returns_mid(self):
        assert elo_to_band(None) == "mid"

    def test_elite(self):
        assert elo_to_band(1300) == "elite"
        assert elo_to_band(1500) == "elite"
        assert elo_to_band(9999) == "elite"

    def test_strong(self):
        assert elo_to_band(1100) == "strong"
        assert elo_to_band(1299) == "strong"

    def test_mid(self):
        assert elo_to_band(900) == "mid"
        assert elo_to_band(1099) == "mid"

    def test_weak(self):
        assert elo_to_band(700) == "weak"
        assert elo_to_band(899) == "weak"

    def test_poor(self):
        assert elo_to_band(699) == "poor"
        assert elo_to_band(0) == "poor"
        assert elo_to_band(-100) == "poor"


# ---------------------------------------------------------------------------
# community_rating_to_band
# ---------------------------------------------------------------------------


class TestCommunityRatingToBand:
    def test_none_returns_mid(self):
        assert community_rating_to_band(None) == "mid"

    def test_elite(self):
        assert community_rating_to_band(80) == "elite"
        assert community_rating_to_band(100) == "elite"

    def test_strong(self):
        assert community_rating_to_band(65) == "strong"
        assert community_rating_to_band(79) == "strong"

    def test_mid(self):
        assert community_rating_to_band(45) == "mid"
        assert community_rating_to_band(64) == "mid"

    def test_weak(self):
        assert community_rating_to_band(25) == "weak"
        assert community_rating_to_band(44) == "weak"

    def test_poor(self):
        assert community_rating_to_band(24) == "poor"
        assert community_rating_to_band(0) == "poor"


# ---------------------------------------------------------------------------
# bands_adjacent
# ---------------------------------------------------------------------------


class TestBandsAdjacent:
    def test_same_band_is_adjacent(self):
        for band in BAND_ORDER:
            assert bands_adjacent(band, band) is True

    def test_neighboring_bands_adjacent(self):
        assert bands_adjacent("elite", "strong") is True
        assert bands_adjacent("strong", "elite") is True
        assert bands_adjacent("mid", "strong") is True
        assert bands_adjacent("mid", "weak") is True
        assert bands_adjacent("weak", "poor") is True

    def test_non_adjacent_bands(self):
        assert bands_adjacent("elite", "mid") is False
        assert bands_adjacent("elite", "weak") is False
        assert bands_adjacent("elite", "poor") is False
        assert bands_adjacent("strong", "poor") is False

    def test_boundary_bands(self):
        # elite has no band above, poor has no band below
        assert bands_adjacent("elite", "elite") is True
        assert bands_adjacent("poor", "poor") is True


# ---------------------------------------------------------------------------
# _film_band
# ---------------------------------------------------------------------------


class TestFilmBand:
    def test_ranked_film_uses_elo(self):
        um = _make_user_movie(elo=1350, battles=5, community_rating=30)
        assert _film_band(um) == "elite"  # elo=1350 -> elite, ignores CR=30

    def test_unranked_film_uses_community_rating(self):
        um = _make_user_movie(elo=None, battles=0, community_rating=85)
        assert _film_band(um) == "elite"

    def test_unranked_no_community_rating_is_mid(self):
        um = _make_user_movie(elo=None, battles=0, community_rating=None)
        assert _film_band(um) == "mid"

    def test_ranked_with_none_elo_uses_elo_band(self):
        # battles >= 1 means ranked, even if elo is somehow None
        um = _make_user_movie(elo=None, battles=1, community_rating=80)
        assert _film_band(um) == "mid"  # elo_to_band(None) = "mid"


# ---------------------------------------------------------------------------
# _band_filtered_candidates
# ---------------------------------------------------------------------------


class TestBandFilteredCandidates:
    def test_same_band_preferred(self):
        anchor_band = "elite"
        c1 = _make_user_movie(elo=1400, battles=5)  # elite
        c2 = _make_user_movie(elo=1100, battles=5)  # strong
        c3 = _make_user_movie(elo=1350, battles=3)  # elite
        result = _band_filtered_candidates(anchor_band, [c1, c2, c3])
        assert c1 in result
        assert c3 in result
        assert c2 not in result

    def test_adjacent_fallback(self):
        anchor_band = "elite"
        c1 = _make_user_movie(elo=900, battles=5)  # mid
        c2 = _make_user_movie(elo=1150, battles=5)  # strong (adjacent to elite)
        result = _band_filtered_candidates(anchor_band, [c1, c2])
        assert c2 in result
        assert c1 not in result

    def test_full_fallback_when_no_adjacent(self):
        anchor_band = "elite"
        c1 = _make_user_movie(elo=700, battles=5)  # weak
        c2 = _make_user_movie(elo=600, battles=5)  # poor
        result = _band_filtered_candidates(anchor_band, [c1, c2])
        # Neither same nor adjacent -> full pool
        assert c1 in result
        assert c2 in result


# ---------------------------------------------------------------------------
# _weighted_sample (settlement weight)
# ---------------------------------------------------------------------------


class TestWeightedSample:
    def test_returns_single_film(self):
        films = [_make_user_movie(battles=0), _make_user_movie(battles=10)]
        result = _weighted_sample(films)
        assert result in films

    def test_settlement_weight_formula(self):
        """Films with fewer battles should have higher weight = 1/(battles+1)."""
        low_battles = _make_user_movie(battles=0)  # weight=1.0
        high_battles = _make_user_movie(battles=99)  # weight=0.01
        with unittest.mock.patch("backend.services.pair_selection.random.choices") as mock_choices:
            mock_choices.return_value = [low_battles]
            result = _weighted_sample([low_battles, high_battles])
            assert result is low_battles
            # Verify weights passed to random.choices
            call_args = mock_choices.call_args
            weights = call_args[1]["weights"] if "weights" in call_args[1] else call_args[0][1]
            # weight for low_battles = 1/(0+1) = 1.0, for high_battles = 1/(99+1) = 0.01
            assert weights[0] == pytest.approx(1.0)
            assert weights[1] == pytest.approx(0.01)
            assert weights[0] > weights[1] * 5

    def test_single_film_list(self):
        film = _make_user_movie(battles=5)
        assert _weighted_sample([film]) is film


# ---------------------------------------------------------------------------
# _pick_challenger
# ---------------------------------------------------------------------------


class TestPickChallenger:
    def test_returns_from_candidates(self):
        anchor = _make_user_movie(elo=1000, battles=5)
        candidates = [
            _make_user_movie(elo=1010, battles=3),
            _make_user_movie(elo=800, battles=7),
        ]
        random.seed(42)
        result = _pick_challenger(anchor, candidates)
        assert result in candidates

    def test_close_match_preference(self):
        """When roll < 0.7, _pick_challenger should prefer close ELO matches."""
        anchor = _make_user_movie(elo=1000, battles=5)
        close = _make_user_movie(elo=1020, battles=5)
        far = _make_user_movie(elo=1500, battles=5)
        with unittest.mock.patch("backend.services.pair_selection.random.random", return_value=0.3):
            with unittest.mock.patch(
                "backend.services.pair_selection.random.choices",
                side_effect=lambda population, weights, k: [population[0]],
            ):
                result = _pick_challenger(anchor, [close, far])
                assert result is close

    def test_falls_back_to_unranked_candidates(self):
        """When no ranked candidates, falls back to settlement-weighted sample."""
        anchor = _make_user_movie(elo=1000, battles=5)
        unranked = _make_user_movie(elo=None, battles=0)
        result = _pick_challenger(anchor, [unranked])
        assert result is unranked


# ---------------------------------------------------------------------------
# _pick_bootstrap_pair
# ---------------------------------------------------------------------------


class TestPickBootstrapPair:
    def test_returns_two_different_films(self):
        films = [_make_user_movie() for _ in range(5)]
        a, b = _pick_bootstrap_pair(films, None)
        assert a is not b

    def test_avoids_last_pair(self):
        f1 = _make_user_movie(movie_id=uuid.UUID("00000000-0000-0000-0000-000000000001"))
        f2 = _make_user_movie(movie_id=uuid.UUID("00000000-0000-0000-0000-000000000002"))
        f3 = _make_user_movie(movie_id=uuid.UUID("00000000-0000-0000-0000-000000000003"))
        last_ids = {str(f1.movie_id), str(f2.movie_id)}
        # With 3 films and one pair excluded, should find a different pair
        random.seed(42)
        a, b = _pick_bootstrap_pair([f1, f2, f3], last_ids)
        pair_ids = {str(a.movie_id), str(b.movie_id)}
        # Should not repeat the last pair (high probability with 3 films)
        # Note: there's a small chance of repetition after 5 retries
        # but with seed=42 this should work
        assert pair_ids != last_ids or len([f1, f2, f3]) == 2

    def test_only_2_films(self):
        f1 = _make_user_movie()
        f2 = _make_user_movie()
        a, b = _pick_bootstrap_pair([f1, f2], None)
        assert {a, b} == {f1, f2}
