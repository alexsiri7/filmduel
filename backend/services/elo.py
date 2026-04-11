"""ELO rating calculation.

Uses the standard ELO formula with K=32.
"""

import math

K_FACTOR = 32


def expected_score(rating_a: float, rating_b: float) -> float:
    """Calculate the expected score for player A given both ratings.

    Returns a value between 0 and 1 representing A's expected win probability.
    """
    return 1.0 / (1.0 + math.pow(10, (rating_b - rating_a) / 400.0))


def update_elo(
    rating_a: float,
    rating_b: float,
    score_a: float,
    k: int = K_FACTOR,
) -> tuple[float, float]:
    """Compute new ELO ratings after a match.

    Args:
        rating_a: Current ELO rating of player A.
        rating_b: Current ELO rating of player B.
        score_a: Actual score for A (1.0 = win, 0.0 = loss, 0.5 = draw).
        k: K-factor controlling rating volatility.

    Returns:
        Tuple of (new_rating_a, new_rating_b).
    """
    ea = expected_score(rating_a, rating_b)
    eb = 1.0 - ea
    score_b = 1.0 - score_a

    new_a = rating_a + k * (score_a - ea)
    new_b = rating_b + k * (score_b - eb)

    return round(new_a, 2), round(new_b, 2)


def outcome_to_scores(outcome: str) -> tuple[float, float]:
    """Convert a duel outcome string to (score_a, score_b).

    Outcomes:
        a_wins  -> (1.0, 0.0)
        b_wins  -> (0.0, 1.0)
        a_only  -> (1.0, 0.0)  A is liked, B is disliked
        b_only  -> (0.0, 1.0)  B is liked, A is disliked
        neither -> (0.0, 0.0)  Both disliked, no ELO change
    """
    mapping = {
        "a_wins": (1.0, 0.0),
        "b_wins": (0.0, 1.0),
        "a_only": (1.0, 0.0),
        "b_only": (0.0, 1.0),
        "neither": (0.0, 0.0),
    }
    return mapping[outcome]
