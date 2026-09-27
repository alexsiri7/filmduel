"""Tests for ELO calculation logic."""

from backend.services.elo import (
    elo_to_rating,
    expected_score,
    get_initial_elo,
    k_factor,
    trakt_rating_to_seeded_elo,
    update_elo,
)


# --- k_factor ---


def test_k_factor_provisional():
    """Battles 0-4 should return K=64."""
    for b in range(5):
        assert k_factor(b) == 64, f"Expected 64 for {b} battles"


def test_k_factor_established():
    """Battles 5+ should return K=32."""
    for b in (5, 10, 100):
        assert k_factor(b) == 32, f"Expected 32 for {b} battles"


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


def test_update_elo_equal_established():
    """Two established players at equal rating: winner gains K/2 = 16."""
    new_w, new_l = update_elo(1000, 1000, winner_battles=10, loser_battles=10)
    assert new_w == 1016
    assert new_l == 984


def test_update_elo_provisional_winner():
    """Provisional winner (K=64) vs established loser (K=32) at equal rating."""
    new_w, new_l = update_elo(1000, 1000, winner_battles=2, loser_battles=10)
    # winner gains 64 * 0.5 = 32, loser loses 32 * 0.5 = 16
    assert new_w == 1032
    assert new_l == 984


def test_update_elo_provisional_loser():
    """Established winner (K=32) vs provisional loser (K=64) at equal rating."""
    new_w, new_l = update_elo(1000, 1000, winner_battles=10, loser_battles=2)
    # winner gains 32 * 0.5 = 16, loser loses 64 * 0.5 = 32
    assert new_w == 1016
    assert new_l == 968


def test_update_elo_both_provisional():
    """Two provisional players at equal rating."""
    new_w, new_l = update_elo(1000, 1000, winner_battles=0, loser_battles=0)
    # both K=64: winner gains 32, loser loses 32
    assert new_w == 1032
    assert new_l == 968


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
