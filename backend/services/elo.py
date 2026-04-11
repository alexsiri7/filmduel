"""ELO rating calculation.

Uses the standard ELO formula with K=32, default rating 1000.
"""

K_FACTOR = 32


def expected_score(rating_a: int, rating_b: int) -> float:
    """Calculate the expected score for player A given both ratings."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400))


def update_elo(
    rating_a: int,
    rating_b: int,
    score_a: float,
    k: int = K_FACTOR,
) -> tuple[int, int]:
    """Compute new ELO ratings after a match.

    Args:
        rating_a: Current ELO rating of player A.
        rating_b: Current ELO rating of player B.
        score_a: Actual score for A (1.0 = win, 0.0 = loss).
        k: K-factor controlling rating volatility.

    Returns:
        Tuple of (new_rating_a, new_rating_b).
    """
    ea = expected_score(rating_a, rating_b)
    score_b = 1.0 - score_a

    new_a = round(rating_a + k * (score_a - ea))
    new_b = round(rating_b + k * (score_b - (1.0 - ea)))

    return new_a, new_b


def outcome_to_scores(outcome: str) -> tuple[float, float]:
    """Convert a duel outcome string to (score_a, score_b).

    Outcomes:
        a_wins  -> (1.0, 0.0)
        b_wins  -> (0.0, 1.0)
        a_only  -> (1.0, 0.0)  A seen, B not
        b_only  -> (0.0, 1.0)  B seen, A not
        neither -> (0.0, 0.0)  Both unseen, no ELO change
    """
    mapping = {
        "a_wins": (1.0, 0.0),
        "b_wins": (0.0, 1.0),
        "a_only": (1.0, 0.0),
        "b_only": (0.0, 1.0),
        "neither": (0.0, 0.0),
    }
    return mapping[outcome]


def trakt_rating_to_elo(trakt_rating: int) -> int:
    """Convert a Trakt rating (1-10) to starting ELO.

    Maps 1->600, 5.5->1000, 10->1400.
    """
    return round(600 + (trakt_rating - 1) * (800 / 9))


def elo_to_trakt_rating(elo: int) -> int:
    """Convert ELO to Trakt's 1-10 scale."""
    return max(1, min(10, round((elo - 600) * 9 / 800) + 1))
