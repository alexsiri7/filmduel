"""ELO rating calculation.

Uses the standard ELO formula with per-player K factors based on battle
count (provisional K=64 for fewer than 5 battles, otherwise K=32).
Default starting rating is 1000.
"""

PROVISIONAL_THRESHOLD = 5
K_PROVISIONAL = 64
K_ESTABLISHED = 32
DEFAULT_ELO = 1000


def k_factor(battles: int) -> int:
    """Return K factor based on number of battles played.

    Provisional players (< 5 battles) get K=64 for faster convergence.
    Established players get K=32.
    """
    return K_PROVISIONAL if battles < PROVISIONAL_THRESHOLD else K_ESTABLISHED


def expected_score(rating_a: int, rating_b: int) -> float:
    """Calculate the expected score for player A given both ratings."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def update_elo(
    winner_elo: int,
    loser_elo: int,
    winner_battles: int,
    loser_battles: int,
) -> tuple[int, int]:
    """Compute new ELO ratings after a match.

    Each player's K factor is determined independently by their battle count,
    so a provisional player's rating moves more than an established player's.

    Args:
        winner_elo: Current ELO rating of the winner.
        loser_elo: Current ELO rating of the loser.
        winner_battles: Number of battles the winner has played (before this one).
        loser_battles: Number of battles the loser has played (before this one).

    Returns:
        Tuple of (new_winner_elo, new_loser_elo).
    """
    e_winner = expected_score(winner_elo, loser_elo)
    e_loser = 1.0 - e_winner

    k_winner = k_factor(winner_battles)
    k_loser = k_factor(loser_battles)

    new_winner = round(winner_elo + k_winner * (1.0 - e_winner))
    new_loser = round(loser_elo + k_loser * (0.0 - e_loser))

    return new_winner, new_loser


def trakt_rating_to_seeded_elo(rating: int) -> int:
    """Convert a Trakt rating (1-10) to a seeded ELO.

    Maps 1->600, 5->~956, 10->1400.
    """
    return round(600 + (rating - 1) * (800 / 9))


def elo_to_trakt_rating(elo: int) -> int:
    """Convert ELO to Trakt's 1-10 scale."""
    return max(1, min(10, round((elo - 600) * 9 / 800) + 1))


def get_initial_elo(seeded_elo: int | None) -> int:
    """Return the starting ELO for a film.

    Uses the seeded ELO (derived from Trakt rating) if available,
    otherwise falls back to the default 1000.
    """
    return seeded_elo if seeded_elo is not None else DEFAULT_ELO
