"""Tests for Pydantic request/response schemas."""

import pytest
from pydantic import ValidationError

from backend.schemas import (
    DuelOutcome,
    DuelResult,
    DuelSubmit,
    MoviePairResponse,
    MovieSchema,
    MovieWithStateSchema,
    RankedMovie,
    RankingsResponse,
    StatsResponse,
    SwipeCardSchema,
    SwipeResponse,
    SwipeResultItem,
    SwipeSubmit,
    UserResponse,
)


# ---------------------------------------------------------------------------
# DuelOutcome enum
# ---------------------------------------------------------------------------


class TestDuelOutcome:
    def test_all_values_exist(self):
        assert DuelOutcome.a_wins == "a_wins"
        assert DuelOutcome.b_wins == "b_wins"
        assert DuelOutcome.a_only == "a_only"
        assert DuelOutcome.b_only == "b_only"
        assert DuelOutcome.neither == "neither"
        assert DuelOutcome.draw == "draw"

    def test_has_exactly_six_members(self):
        assert len(DuelOutcome) == 6

    def test_is_string_enum(self):
        assert isinstance(DuelOutcome.a_wins, str)
        assert DuelOutcome.a_wins == "a_wins"


# ---------------------------------------------------------------------------
# DuelSubmit
# ---------------------------------------------------------------------------


class TestDuelSubmit:
    def test_valid_submit(self):
        ds = DuelSubmit(
            movie_a_id="550e8400-e29b-41d4-a716-446655440000",
            movie_b_id="550e8400-e29b-41d4-a716-446655440001",
            outcome=DuelOutcome.a_wins,
        )
        assert ds.movie_a_id == "550e8400-e29b-41d4-a716-446655440000"
        assert ds.outcome == DuelOutcome.a_wins
        assert ds.mode == "discovery"  # default

    def test_custom_mode(self):
        ds = DuelSubmit(
            movie_a_id="abc",
            movie_b_id="def",
            outcome=DuelOutcome.b_wins,
            mode="ranking",
        )
        assert ds.mode == "ranking"

    def test_invalid_outcome_rejected(self):
        with pytest.raises(ValidationError):
            DuelSubmit(
                movie_a_id="abc",
                movie_b_id="def",
                outcome="invalid_outcome",
            )

    def test_missing_movie_ids_rejected(self):
        with pytest.raises(ValidationError):
            DuelSubmit(outcome=DuelOutcome.a_wins)

    def test_all_outcome_values_accepted(self):
        for outcome in DuelOutcome:
            ds = DuelSubmit(
                movie_a_id="a", movie_b_id="b", outcome=outcome
            )
            assert ds.outcome == outcome


# ---------------------------------------------------------------------------
# SwipeSubmit / SwipeResultItem
# ---------------------------------------------------------------------------


class TestSwipeSubmit:
    def test_valid_submit(self):
        ss = SwipeSubmit(
            results=[
                SwipeResultItem(movie_id="abc-123", seen=True),
                SwipeResultItem(movie_id="def-456", seen=False),
            ]
        )
        assert len(ss.results) == 2
        assert ss.results[0].seen is True
        assert ss.results[1].seen is False

    def test_empty_results_valid(self):
        ss = SwipeSubmit(results=[])
        assert ss.results == []

    def test_missing_results_rejected(self):
        with pytest.raises(ValidationError):
            SwipeSubmit()

    def test_invalid_result_item_rejected(self):
        with pytest.raises(ValidationError):
            SwipeSubmit(results=[{"movie_id": "abc"}])  # missing 'seen'


# ---------------------------------------------------------------------------
# MovieSchema
# ---------------------------------------------------------------------------


class TestMovieSchema:
    def test_required_fields_only(self):
        m = MovieSchema(id="1", trakt_id=42, title="Blade Runner")
        assert m.id == "1"
        assert m.trakt_id == 42
        assert m.title == "Blade Runner"
        assert m.year is None
        assert m.poster_url is None
        assert m.tmdb_id is None
        assert m.imdb_id is None
        assert m.overview is None

    def test_all_fields(self):
        m = MovieSchema(
            id="1",
            trakt_id=42,
            tmdb_id=100,
            imdb_id="tt0083658",
            title="Blade Runner",
            year=1982,
            poster_url="https://example.com/poster.jpg",
            overview="A classic.",
        )
        assert m.year == 1982
        assert m.tmdb_id == 100

    def test_missing_required_rejected(self):
        with pytest.raises(ValidationError):
            MovieSchema(id="1")  # missing trakt_id, title


# ---------------------------------------------------------------------------
# MovieWithStateSchema
# ---------------------------------------------------------------------------


class TestMovieWithStateSchema:
    def test_inherits_movie_fields(self):
        m = MovieWithStateSchema(
            id="1", trakt_id=42, title="Test", seen=True, elo=1200, battles=5
        )
        assert m.title == "Test"
        assert m.seen is True
        assert m.elo == 1200
        assert m.battles == 5

    def test_defaults(self):
        m = MovieWithStateSchema(id="1", trakt_id=42, title="Test")
        assert m.seen is None
        assert m.elo is None
        assert m.battles == 0
        assert m.genres is None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TestResponseModels:
    def test_duel_result(self):
        dr = DuelResult(
            outcome=DuelOutcome.a_wins,
            movie_a_elo_delta=16,
            movie_b_elo_delta=-16,
        )
        assert dr.next_action == "duel"  # default
        assert dr.movie_a_elo_delta == 16

    def test_duel_result_swipe_action(self):
        dr = DuelResult(
            outcome=DuelOutcome.b_wins,
            movie_a_elo_delta=-32,
            movie_b_elo_delta=32,
            next_action="swipe",
        )
        assert dr.next_action == "swipe"

    def test_ranked_movie(self):
        rm = RankedMovie(
            rank=1,
            movie=MovieSchema(id="1", trakt_id=1, title="Top"),
            elo=1500,
            battles=20,
        )
        assert rm.rank == 1
        assert rm.elo == 1500

    def test_ranked_movie_defaults(self):
        rm = RankedMovie(
            rank=1,
            movie=MovieSchema(id="1", trakt_id=1, title="Top"),
        )
        assert rm.elo == 1000
        assert rm.battles == 0

    def test_rankings_response(self):
        rr = RankingsResponse(rankings=[], total=0)
        assert rr.total == 0
        assert rr.rankings == []

    def test_swipe_card_schema(self):
        sc = SwipeCardSchema(id="1", trakt_id=10, title="Movie")
        assert sc.genres == []
        assert sc.year is None
        assert sc.community_rating is None

    def test_swipe_response(self):
        sr = SwipeResponse(seen_count=5, unseen_count=3)
        assert sr.next_action == "duel"

    def test_swipe_response_swipe_action(self):
        sr = SwipeResponse(seen_count=1, unseen_count=8, next_action="swipe")
        assert sr.next_action == "swipe"

    def test_stats_response_minimal(self):
        st = StatsResponse(
            total_duels=0, total_movies_ranked=0, average_elo=0.0
        )
        assert st.unseen_count == 0
        assert st.highest_rated is None
        assert st.lowest_rated is None

    def test_user_response(self):
        from datetime import datetime, timezone

        ur = UserResponse(
            id="abc", trakt_username="testuser", created_at=datetime.now(timezone.utc)
        )
        assert ur.trakt_username == "testuser"

    def test_movie_pair_response(self):
        ma = MovieWithStateSchema(id="1", trakt_id=1, title="A")
        mb = MovieWithStateSchema(id="2", trakt_id=2, title="B")
        pr = MoviePairResponse(movie_a=ma, movie_b=mb)
        assert pr.next_pair_token is None
        assert pr.movie_a.title == "A"
