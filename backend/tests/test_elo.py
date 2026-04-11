"""Tests for ELO calculation logic."""

from backend.services.elo import expected_score, update_elo


def test_expected_score_equal_ratings():
    assert expected_score(1000, 1000) == 0.5


def test_expected_score_higher_rated_favored():
    assert expected_score(1200, 1000) > 0.5
    assert expected_score(1000, 1200) < 0.5


def test_expected_scores_sum_to_one():
    e1 = expected_score(1200, 1000)
    e2 = expected_score(1000, 1200)
    assert abs(e1 + e2 - 1.0) < 1e-10


def test_update_elo_winner_gains():
    """A wins: score_a=1.0 means A won."""
    new_a, new_b = update_elo(1000, 1000, score_a=1.0)
    assert new_a > 1000
    assert new_b < 1000


def test_update_elo_conserved():
    new_a, new_b = update_elo(1000, 1000, score_a=1.0)
    assert new_a + new_b == 2000


def test_update_elo_equal_ratings_change():
    new_a, _ = update_elo(1000, 1000, score_a=1.0, k=32)
    assert new_a == 1016


def test_health_endpoint():
    from fastapi.testclient import TestClient
    from backend.main import app

    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
