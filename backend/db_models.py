"""SQLAlchemy 2.0 ORM models — source of truth for database schema."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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
    community_rating: Mapped[Optional[float]] = mapped_column(Numeric(4, 1), nullable=True)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class UserMovie(Base):
    __tablename__ = "user_movies"
    __table_args__ = (
        UniqueConstraint("user_id", "movie_id"),
        Index("ix_user_movies_user_id", "user_id"),
        Index("ix_user_movies_user_seen", "user_id", "seen"),
        Index(
            "ix_user_movies_user_elo",
            "user_id",
            "elo",
            postgresql_where="elo IS NOT NULL",
        ),
        Index(
            "ix_user_movies_user_seen_battles",
            "user_id",
            "seen",
            "battles",
            postgresql_where="seen = true",
        ),
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
    elo: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    seeded_elo: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
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


class Tournament(Base):
    __tablename__ = "tournaments"
    __table_args__ = (Index("ix_tournaments_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    filter_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    filter_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    bracket_size: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="active"
    )
    champion_movie_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("movies.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    tagline: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    theme_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_ai_curated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    llm_response: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship()
    champion_movie: Mapped[Optional[Movie]] = relationship(
        foreign_keys=[champion_movie_id]
    )
    matches: Mapped[list[TournamentMatch]] = relationship(
        back_populates="tournament", cascade="all, delete-orphan"
    )


class TournamentMatch(Base):
    __tablename__ = "tournament_matches"
    __table_args__ = (
        UniqueConstraint("tournament_id", "round", "position"),
        Index("ix_tournament_matches_tournament_id", "tournament_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tournament_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tournaments.id", ondelete="CASCADE"),
        nullable=False,
    )
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    movie_a_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("movies.id"), nullable=True
    )
    movie_b_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("movies.id"), nullable=True
    )
    winner_movie_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("movies.id"), nullable=True
    )
    duel_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("duels.id"), nullable=True
    )
    is_bye: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    played_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tournament: Mapped[Tournament] = relationship(back_populates="matches")
    movie_a: Mapped[Optional[Movie]] = relationship(foreign_keys=[movie_a_id])
    movie_b: Mapped[Optional[Movie]] = relationship(foreign_keys=[movie_b_id])
    winner_movie: Mapped[Optional[Movie]] = relationship(
        foreign_keys=[winner_movie_id]
    )
    duel: Mapped[Optional[Duel]] = relationship()


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
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="discovery")
    pair_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped[User] = relationship(back_populates="duels")
    winner_movie: Mapped[Optional[Movie]] = relationship(foreign_keys=[winner_movie_id])
    loser_movie: Mapped[Optional[Movie]] = relationship(foreign_keys=[loser_movie_id])


class PoolExpansion(Base):
    __tablename__ = "pool_expansions"
    __table_args__ = (
        Index("ix_pool_expansions_user_source_key", "user_id", "source", "source_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    films_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class Suggestion(Base):
    __tablename__ = "suggestions"
    __table_args__ = (
        Index("ix_suggestions_user_id", "user_id"),
        Index(
            "ix_suggestions_user_active",
            "user_id",
            "dismissed_at",
            postgresql_where="dismissed_at IS NULL",
        ),
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
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    added_to_watchlist_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped[User] = relationship()
    movie: Mapped[Movie] = relationship()


class FeedbackReport(Base):
    __tablename__ = "feedback_reports"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    screenshot_data: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    user: Mapped[User] = relationship()


class SwipeResult(Base):
    __tablename__ = "swipe_results"
    __table_args__ = (Index("ix_swipe_results_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    movie_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("movies.id", ondelete="CASCADE"), nullable=False
    )
    seen: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
