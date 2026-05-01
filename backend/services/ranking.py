"""Shared SQL: base SELECT for a user's ranked films."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select

from backend.db_models import Movie, UserMovie


def ranked_user_movies_stmt(
    user_id: uuid.UUID, media_type: str | None = None
) -> Select:
    """Base SELECT for a user's ranked films (seen, battled, elo set).

    Joins Movie. Caller adds .order_by / .limit / additional .where as needed.
    """
    stmt = (
        select(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            UserMovie.battles >= 1,
            UserMovie.elo.isnot(None),
        )
    )
    if media_type is not None:
        stmt = stmt.where(Movie.media_type == media_type)
    return stmt
