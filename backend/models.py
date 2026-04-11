"""SQLAlchemy 2.0 ORM models and Pydantic schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ── SQLAlchemy ORM models ────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trakt_user_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    trakt_username: Mapped[str] = mapped_column(Text, nullable=False)
    trakt_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    trakt_refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    trakt_token_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user_movies: Mapped[list[UserMovie]] = relationship(back_populates="user", cascade="all, delete-orphan")
    duels: Mapped[list[Duel]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Movie(Base):
    __tablename__ = "movies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    trakt_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    imdb_id: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tmdb_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    genres: Mapped[Optional[list[str]]] = mapped_column(ARRAY(Text), nullable=True)
    overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    runtime: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    poster_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class UserMovie(Base):
    __tablename__ = "user_movies"
    __table_args__ = (
        UniqueConstraint("user_id", "movie_id"),
        Index("ix_user_movies_user_id", "user_id"),
        Index("ix_user_movies_user_seen", "user_id", "seen"),
        Index("ix_user_movies_user_elo", "user_id", "elo"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    movie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("movies.id", ondelete="CASCADE"), nullable=False
    )
    seen: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    elo: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    battles: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trakt_rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_dueled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped[User] = relationship(back_populates="user_movies")
    movie: Mapped[Movie] = relationship()


class Duel(Base):
    __tablename__ = "duels"
    __table_args__ = (Index("ix_duels_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    winner_movie_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("movies.id"), nullable=True
    )
    loser_movie_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("movies.id"), nullable=True
    )
    winner_elo_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    loser_elo_before: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    winner_elo_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    loser_elo_after: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped[User] = relationship(back_populates="duels")
    winner_movie: Mapped[Optional[Movie]] = relationship(foreign_keys=[winner_movie_id])
    loser_movie: Mapped[Optional[Movie]] = relationship(foreign_keys=[loser_movie_id])


# ── Pydantic schemas (API request/response) ─────────────────────────


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


class MoviePairResponse(BaseModel):
    movie_a: MovieSchema
    movie_b: MovieSchema


class DuelOutcome(str, Enum):
    a_wins = "a_wins"
    b_wins = "b_wins"
    a_only = "a_only"
    b_only = "b_only"
    neither = "neither"


class DuelSubmit(BaseModel):
    movie_a_id: str
    movie_b_id: str
    outcome: DuelOutcome


class DuelResult(BaseModel):
    outcome: DuelOutcome
    movie_a_elo_delta: int
    movie_b_elo_delta: int


class RankedMovie(BaseModel):
    rank: int
    movie: MovieSchema
    elo: int = 1000
    battles: int = 0


class RankingsResponse(BaseModel):
    rankings: list[RankedMovie]
    total: int


class StatsResponse(BaseModel):
    total_duels: int
    total_movies_ranked: int
    unseen_count: int = 0
    average_elo: float
    highest_rated: Optional[RankedMovie] = None
    lowest_rated: Optional[RankedMovie] = None
