"""Tests for ELO calculation logic."""

import itertools
import math
import random

import pytest

from backend.services.elo import (
    elo_to_rating,
    expected_score,
    get_initial_elo,
    k_factor,
    trakt_rating_to_seeded_elo,
    update_elo,
)


# --- k_factor ---


def test_k_factor_shrinks_with_battles():
    assert k_factor(0) == 300
    assert k_factor(3) == 150
    assert k_factor(8) == 100


def test_k_factor_strictly_decreasing():
    ks = [k_factor(b) for b in range(200)]
    assert all(a > b for a, b in zip(ks, ks[1:]))


# --- expected_score ---


def test_expected_score_equal_ratings():
    assert expected_score(1000, 1000) == 0.5


def test_expected_score_higher_rated_favored():
    assert expected_score(1200, 1000) > 0.5
    assert expected_score(1000, 1200) < 0.5


def test_expected_scores_sum_to_one():
    e1 = expected_score(1200, 1000)
    e2 = expected_score(1000, 1200)
    assert abs(e1 + e2 - 1.0) < 1e-10


# --- update_elo ---


def test_update_elo_winner_gains():
    new_w, new_l = update_elo(1000, 1000, winner_battles=10, loser_battles=10)
    assert new_w > 1000
    assert new_l < 1000


def test_update_elo_equal_ratings_equal_battles():
    """K = 300/sqrt(4) = 150 each: winner gains 75, loser loses 75."""
    new_w, new_l = update_elo(1000, 1000, winner_battles=3, loser_battles=3)
    assert new_w == pytest.approx(1075.0)
    assert new_l == pytest.approx(925.0)


def test_update_elo_new_winner_vs_established_loser():
    """K 300 for the winner, 100 for the loser, at equal rating."""
    new_w, new_l = update_elo(1000, 1000, winner_battles=0, loser_battles=8)
    assert new_w == pytest.approx(1150.0)
    assert new_l == pytest.approx(950.0)


def test_update_elo_established_winner_vs_new_loser():
    new_w, new_l = update_elo(1000, 1000, winner_battles=8, loser_battles=0)
    assert new_w == pytest.approx(1050.0)
    assert new_l == pytest.approx(850.0)


def test_update_elo_keeps_fractional_ratings():
    new_w, new_l = update_elo(1000, 1000, winner_battles=10, loser_battles=10)
    assert new_w == pytest.approx(1000 + 150 / math.sqrt(11))
    assert new_l == pytest.approx(1000 - 150 / math.sqrt(11))
    assert new_w != round(new_w)


# --- trakt_rating_to_seeded_elo ---


def test_trakt_rating_to_seeded_elo_min():
    assert trakt_rating_to_seeded_elo(1) == 600


def test_trakt_rating_to_seeded_elo_mid():
    elo = trakt_rating_to_seeded_elo(5)
    # (5-1) * 800/9 + 600 = 955.56 -> 956
    assert elo == 956


def test_trakt_rating_to_seeded_elo_max():
    assert trakt_rating_to_seeded_elo(10) == 1400


# --- elo_to_rating ---


def test_elo_to_rating_ten_films_fill_the_scale_on_a_narrow_range():
    elos = [813, 850, 900, 940, 1000, 1050, 1100, 1150, 1250, 1342]
    assert [elo_to_rating(e, elos) for e in elos] == list(range(1, 11))


def test_elo_to_rating_clumped_population_splits_into_equal_deciles():
    elos = list(range(950, 1050))
    ratings = [elo_to_rating(e, elos) for e in elos]
    assert all(ratings.count(r) == 10 for r in range(1, 11))
    assert ratings == sorted(ratings)


def test_elo_to_rating_ties_share_a_rating():
    elos = [900, 1000, 1000, 1100]
    assert elo_to_rating(1000, elos) == 5
    assert elo_to_rating(1000, [1000] * 7) == 5


def test_elo_to_rating_small_populations():
    assert elo_to_rating(1000, [1000]) == 5
    assert elo_to_rating(900, [900, 1100]) == 3
    assert elo_to_rating(1100, [900, 1100]) == 8


def test_elo_to_rating_outside_population_and_empty():
    elos = [900, 1000, 1100]
    assert elo_to_rating(500, elos) == 1
    assert elo_to_rating(2000, elos) == 10
    assert elo_to_rating(1000, []) == 5


# --- get_initial_elo ---


def test_get_initial_elo_with_seed():
    assert get_initial_elo(1200) == 1200


def test_get_initial_elo_without_seed():
    assert get_initial_elo(None) == 1000


# --- properties ---

RATINGS = (600, 900, 1000, 1000.5, 1100, 1400)
BATTLES = (0, 1, 4, 5, 20, 400)


def test_expected_score_is_symmetric():
    for a, b in itertools.product(RATINGS, repeat=2):
        assert expected_score(a, b) + expected_score(b, a) == pytest.approx(1)


def test_update_elo_is_zero_sum_at_equal_battles():
    for w, l, battles in itertools.product(RATINGS, RATINGS, BATTLES):
        new_w, new_l = update_elo(w, l, battles, battles)
        assert new_w - w == pytest.approx(l - new_l)


def test_update_elo_depends_only_on_the_rating_gap():
    for w, l, bw, bl in itertools.product(RATINGS, RATINGS, BATTLES, BATTLES):
        new_w, new_l = update_elo(w, l, bw, bl)
        shifted_w, shifted_l = update_elo(w + 250, l + 250, bw, bl)
        assert shifted_w - 250 == pytest.approx(new_w)
        assert shifted_l - 250 == pytest.approx(new_l)


def test_update_elo_winner_always_gains_loser_always_loses():
    for w, l, bw, bl in itertools.product(RATINGS, RATINGS, BATTLES, BATTLES):
        new_w, new_l = update_elo(w, l, bw, bl)
        assert new_w > w
        assert new_l < l


def test_update_elo_underdog_gains_more():
    underdog_w, _ = update_elo(900, 1100, 10, 10)
    favourite_w, _ = update_elo(1100, 900, 10, 10)
    assert underdog_w - 900 > favourite_w - 1100


def test_update_elo_is_calibrated_on_simulated_duels():
    """Favourites are not underrated once ratings have warmed up (#649)."""
    predictions: list[tuple[float, bool]] = []
    for seed in range(10):
        rng = random.Random(seed)
        true = [rng.gauss(1000, 200) for _ in range(100)]
        elo = [1000.0] * 100
        battles = [0] * 100
        for duel in range(1000):
            i, j = rng.sample(range(100), 2)
            i_wins = rng.random() < expected_score(true[i], true[j])
            if duel >= 300:
                predictions.append((expected_score(elo[i], elo[j]), i_wins))
            w, l = (i, j) if i_wins else (j, i)
            elo[w], elo[l] = update_elo(elo[w], elo[l], battles[w], battles[l])
            battles[w] += 1
            battles[l] += 1

    log_loss = -sum(
        math.log(p if won else 1 - p) for p, won in predictions
    ) / len(predictions)
    favourite = [(p, won) if p >= 0.5 else (1 - p, not won) for p, won in predictions]
    predicted = sum(p for p, _ in favourite) / len(favourite)
    actual = sum(won for _, won in favourite) / len(favourite)

    assert log_loss < 0.65
    assert actual - predicted < 0.02
    assert actual - predicted > -0.08
