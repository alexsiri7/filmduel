"""Pydantic request/response schemas — API contract, separate from ORM models."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

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


class StatsResponse(BaseModel):
    total_duels: int
    total_movies_ranked: int
    unseen_count: int = 0
    average_elo: float
    highest_rated: Optional[RankedMovie] = None
    lowest_rated: Optional[RankedMovie] = None
