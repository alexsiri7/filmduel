"""ELO rating calculation.

Uses the standard ELO formula with an uncertainty-aware, per-player K factor
K = K0/sqrt(battles+1), so a film's rating settles as it plays more duels.
Ratings are kept as unrounded floats. Default starting rating is 1000.
"""

import math
from bisect import bisect_left, bisect_right
from collections.abc import Sequence

# Replaying real duels scored K0=200/300/400 within 0.008 log-loss; 300 was best (#649).
K0 = 300
DEFAULT_ELO = 1000


def k_factor(battles: int) -> float:
    """Return the K factor for a film that has played ``battles`` duels.

    The fewer battles, the less certain its rating, so the more it moves.
    """
    return K0 / math.sqrt(battles + 1)


def expected_score(rating_a: float, rating_b: float) -> float:
    """Calculate the expected score for player A given both ratings."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def update_elo(
    winner_elo: float,
    loser_elo: float,
    winner_battles: int,
    loser_battles: int,
) -> tuple[float, float]:
    """Compute new ELO ratings after a match.

    Each player's K factor is determined independently by their battle count,
    so a film with few battles moves more than a well-established one.

    Args:
        winner_elo: Current ELO rating of the winner.
        loser_elo: Current ELO rating of the loser.
        winner_battles: Number of battles the winner has played (before this one).
        loser_battles: Number of battles the loser has played (before this one).

    Returns:
        Tuple of (new_winner_elo, new_loser_elo), unrounded.
    """
    e_winner = expected_score(winner_elo, loser_elo)
    e_loser = 1.0 - e_winner

    k_winner = k_factor(winner_battles)
    k_loser = k_factor(loser_battles)

    new_winner = winner_elo + k_winner * (1.0 - e_winner)
    new_loser = loser_elo + k_loser * (0.0 - e_loser)

    return new_winner, new_loser


def trakt_rating_to_seeded_elo(rating: int) -> int:
    """Convert a Trakt rating (1-10) to a seeded ELO.

    Maps 1->600, 5->~956, 10->1400.
    """
    return round(600 + (rating - 1) * (800 / 9))


def elo_to_rating(elo: float, sorted_elos: Sequence[float]) -> int:
    """Map an ELO to the 1-10 scale by its percentile among the user's ranked ELOs.

    ``sorted_elos`` must be ascending. Uses the mid-rank percentile, so N
    distinct films split into N equal slices of the scale and ties share a
    rating. An empty population rates 5.
    """
    n = len(sorted_elos)
    if n == 0:
        return 5
    below = bisect_left(sorted_elos, elo)
    equal = bisect_right(sorted_elos, elo) - below
    # ceil(10 * (below + equal/2) / n) in integer arithmetic, so exact decile
    # boundaries don't round up through float error.
    rating = -(-10 * (2 * below + equal) // (2 * n))
    return max(1, min(10, rating))


def get_initial_elo(seeded_elo: int | None) -> int:
    """Return the starting ELO for a film.

    Uses the seeded ELO (derived from Trakt rating) if available,
    otherwise falls back to the default 1000.
    """
    return seeded_elo if seeded_elo is not None else DEFAULT_ELO
