"""Pydantic request/response schemas — API contract, separate from ORM models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel


class UserResponse(BaseModel):
    id: str
    trakt_username: str
    created_at: datetime


class MovieSchema(BaseModel):
    id: str
    trakt_id: int
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    overview: Optional[str] = None
    genres: Optional[list[str]] = None


class MovieWithStateSchema(MovieSchema):
    """Movie with user-specific state from user_movies."""

    genres: Optional[list[str]] = None
    seen: Optional[bool] = None
    elo: Optional[int] = None
    battles: int = 0


class MoviePairResponse(BaseModel):
    movie_a: MovieWithStateSchema
    movie_b: MovieWithStateSchema
    next_pair_token: Optional[str] = None


class DuelOutcome(str, Enum):
    a_wins = "a_wins"
    b_wins = "b_wins"
    a_only = "a_only"
    b_only = "b_only"
    neither = "neither"
    draw = "draw"


class DuelSubmit(BaseModel):
    movie_a_id: str
    movie_b_id: str
    outcome: DuelOutcome
    mode: str = "discovery"


class DuelResult(BaseModel):
    outcome: DuelOutcome
    movie_a_elo_delta: int
    movie_b_elo_delta: int
    next_action: str = "duel"


class RankedMovie(BaseModel):
    rank: int
    movie: MovieSchema
    elo: int = 1000
    battles: int = 0


class RankingsResponse(BaseModel):
    rankings: list[RankedMovie]
    total: int


class SwipeCardSchema(BaseModel):
    id: str
    trakt_id: int
    title: str
    year: Optional[int] = None
    genres: list[str] = []
    poster_url: Optional[str] = None
    community_rating: Optional[float] = None


class SwipeResultItem(BaseModel):
    movie_id: str
    seen: bool


class SwipeSubmit(BaseModel):
    results: list[SwipeResultItem]


class SwipeResponse(BaseModel):
    seen_count: int
    unseen_count: int
    next_action: str = "duel"  # "duel" or "swipe" — whether user has enough seen films


class StatsResponse(BaseModel):
    total_duels: int
    total_movies_ranked: int
    unseen_count: int = 0
    average_elo: float
    highest_rated: Optional[RankedMovie] = None
    lowest_rated: Optional[RankedMovie] = None


# ── Tournament schemas ──────────────────────────────────────────────


class TournamentCreate(BaseModel):
    name: str
    filter_type: Optional[str] = None
    filter_value: Optional[str] = None
    bracket_size: Literal[8, 16, 32, 64]


class TournamentMatchSchema(BaseModel):
    id: str
    round: int
    position: int
    movie_a: Optional[MovieSchema] = None
    movie_b: Optional[MovieSchema] = None
    winner_movie_id: Optional[str] = None
    is_bye: bool = False
    played_at: Optional[datetime] = None


class TournamentSchema(BaseModel):
    id: str
    name: str
    filter_type: Optional[str] = None
    filter_value: Optional[str] = None
    bracket_size: int
    status: str
    champion_movie_id: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    matches: list[TournamentMatchSchema] = []


class TournamentListItem(BaseModel):
    id: str
    name: str
    bracket_size: int
    status: str
    created_at: datetime
    progress: str = ""


# ── Suggestion schemas ─────────────────────────────────────────────


class SuggestionSchema(BaseModel):
    id: str
    movie: MovieSchema
    reason: str
    generated_at: datetime
    dismissed_at: Optional[datetime] = None
    added_to_watchlist_at: Optional[datetime] = None


class SuggestionsResponse(BaseModel):
    suggestions: list[SuggestionSchema]
    status: str = "ready"  # "ready" | "generating" | "not_enough_films"
