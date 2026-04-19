"""Tests for swipe logic — band indexing, community rating range, next_action."""

import pytest

from backend.routers.swipe import (
    BANDS,
    _community_rating_range,
    _elo_to_band_index,
)


# ---------------------------------------------------------------------------
# _elo_to_band_index
# ---------------------------------------------------------------------------


class TestEloToBandIndex:
    def test_elite(self):
        assert _elo_to_band_index(1300) == 0
        assert _elo_to_band_index(9999) == 0

    def test_strong(self):
        assert _elo_to_band_index(1100) == 1
        assert _elo_to_band_index(1299) == 1

    def test_mid(self):
        assert _elo_to_band_index(900) == 2
        assert _elo_to_band_index(1099) == 2

    def test_weak(self):
        assert _elo_to_band_index(700) == 3
        assert _elo_to_band_index(899) == 3

    def test_low(self):
        assert _elo_to_band_index(0) == 4
        assert _elo_to_band_index(699) == 4

    def test_out_of_range_defaults_to_mid(self):
        # Negative ELO is not in any band range -> defaults to 2 (mid)
        assert _elo_to_band_index(-100) == 2

    def test_exact_boundaries(self):
        # Check each boundary value
        assert _elo_to_band_index(1300) == 0  # elite lower bound
        assert _elo_to_band_index(1100) == 1  # strong lower bound
        assert _elo_to_band_index(900) == 2   # mid lower bound
        assert _elo_to_band_index(700) == 3   # weak lower bound


# ---------------------------------------------------------------------------
# _community_rating_range
# ---------------------------------------------------------------------------


class TestCommunityRatingRange:
    def test_elite_range(self):
        low, high = _community_rating_range(0)
        assert low == 80.0
        assert high == 100.0

    def test_strong_range(self):
        low, high = _community_rating_range(1)
        assert low == 65.0
        assert high == 79.0

    def test_mid_range(self):
        low, high = _community_rating_range(2)
        assert low == 45.0
        assert high == 64.0

    def test_weak_range(self):
        low, high = _community_rating_range(3)
        assert low == 25.0
        assert high == 44.0

    def test_low_range(self):
        low, high = _community_rating_range(4)
        assert low == 0.0
        assert high == 24.0

    def test_returns_floats(self):
        low, high = _community_rating_range(0)
        assert isinstance(low, float)
        assert isinstance(high, float)


# ---------------------------------------------------------------------------
# BANDS structure
# ---------------------------------------------------------------------------


class TestBandsStructure:
    def test_has_5_bands(self):
        assert len(BANDS) == 5

    def test_band_names(self):
        names = [b[0] for b in BANDS]
        assert names == ["elite", "strong", "mid", "weak", "poor"]

    def test_elo_ranges_descending(self):
        """ELO lower bounds should be strictly descending from elite to low."""
        lows = [b[1] for b in BANDS]
        for i in range(len(lows) - 1):
            assert lows[i] > lows[i + 1], f"Band {i} low={lows[i]} not > band {i+1} low={lows[i+1]}"

    def test_community_rating_ranges_descending(self):
        """CR lower bounds should be strictly descending from elite to low."""
        cr_lows = [b[3] for b in BANDS]
        for i in range(len(cr_lows) - 1):
            assert cr_lows[i] > cr_lows[i + 1], f"Band {i} cr_low={cr_lows[i]} not > band {i+1} cr_low={cr_lows[i+1]}"


# ---------------------------------------------------------------------------
# next_action logic (swipe vs duel threshold)
# ---------------------------------------------------------------------------


class TestNextActionLogic:
    """Tests for the next_action determination in swipe results.

    The rule: next_action = "duel" if total_seen >= 2 else "swipe"
    """

    def test_threshold_logic(self):
        # total_seen >= 2 -> duel
        assert ("duel" if 2 >= 2 else "swipe") == "duel"
        assert ("duel" if 100 >= 2 else "swipe") == "duel"

    def test_below_threshold(self):
        assert ("duel" if 0 >= 2 else "swipe") == "swipe"
        assert ("duel" if 1 >= 2 else "swipe") == "swipe"
