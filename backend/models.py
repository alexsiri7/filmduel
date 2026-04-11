"""Pydantic models for API requests and responses."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# --- Auth ---


class UserResponse(BaseModel):
    id: str
    trakt_username: str
    trakt_slug: str
    avatar_url: Optional[str] = None
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# --- Movies ---


class Movie(BaseModel):
    id: str
    trakt_id: int
    tmdb_id: Optional[int] = None
    imdb_id: Optional[str] = None
    title: str
    year: Optional[int] = None
    poster_url: Optional[str] = None
    overview: Optional[str] = None


class MoviePairResponse(BaseModel):
    movie_a: Movie
    movie_b: Movie
    duel_id: str


# --- Duels ---


class DuelOutcome(str, Enum):
    a_wins = "a_wins"
    b_wins = "b_wins"
    a_only = "a_only"
    b_only = "b_only"
    neither = "neither"


class DuelSubmit(BaseModel):
    duel_id: str
    outcome: DuelOutcome


class DuelResult(BaseModel):
    duel_id: str
    outcome: DuelOutcome
    movie_a_elo_delta: float
    movie_b_elo_delta: float


# --- Rankings ---


class RankedMovie(BaseModel):
    rank: int
    movie: Movie
    elo_rating: float = Field(default=1500.0)
    duel_count: int = 0
    win_count: int = 0


class RankingsResponse(BaseModel):
    rankings: list[RankedMovie]
    total: int


class StatsResponse(BaseModel):
    total_duels: int
    total_movies_ranked: int
    average_elo: float
    highest_rated: Optional[RankedMovie] = None
    lowest_rated: Optional[RankedMovie] = None
