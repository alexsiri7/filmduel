"""Personal-data export — GDPR Art. 15 (access) / Art. 20 (portability)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db_models import (
    Duel,
    FeedbackReport,
    Movie,
    PoolExpansion,
    Suggestion,
    SwipeResult,
    Tournament,
    TournamentMatch,
    User,
    UserMovie,
)

# Same safety cap as the rankings CSV export; sections that hit it are named
# in the payload's ``truncated_sections`` rather than silently cut.
EXPORT_ROW_CAP = 10_000


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _movie_ref(movie: Movie | None) -> dict | None:
    if movie is None:
        return None
    return {
        "id": str(movie.id),
        "trakt_id": movie.trakt_id,
        "imdb_id": movie.imdb_id,
        "tmdb_id": movie.tmdb_id,
        "title": movie.title,
        "year": movie.year,
        "media_type": movie.media_type,
    }


def _match(m: TournamentMatch) -> dict:
    return {
        "round": m.round,
        "position": m.position,
        "is_bye": m.is_bye,
        "played_at": _iso(m.played_at),
        "movie_a": _movie_ref(m.movie_a),
        "movie_b": _movie_ref(m.movie_b),
        "winner": _movie_ref(m.winner_movie),
    }


def build_export_payload(
    user: User,
    *,
    user_movies: list[UserMovie],
    duels: list[Duel],
    tournaments: list[Tournament],
    suggestions: list[Suggestion],
    swipe_results: list[SwipeResult],
    feedback_reports: list[FeedbackReport],
    pool_expansions: list[PoolExpansion],
    truncated_sections: list[str],
    exported_at: datetime,
) -> dict:
    """Serialize the user's records into a JSON-native dict.

    Every section is an explicit field allow-list. Never serialize ``User``
    reflectively: ``EncryptedToken`` decrypts on attribute read, so any
    ``vars()``/column loop would put plaintext provider credentials in the
    download. The profile deliberately omits the four ``*_token_enc`` columns
    and their descriptor properties, ``*_token_expires_at`` and
    ``tokens_invalid_before``.
    """
    return {
        "format_version": 1,
        "exported_at": _iso(exported_at),
        "profile": {
            "id": str(user.id),
            "trakt_user_id": user.trakt_user_id,
            "trakt_username": user.trakt_username,
            "simkl_user_id": user.simkl_user_id,
            "simkl_username": user.simkl_username,
            "created_at": _iso(user.created_at),
            "last_seen_at": _iso(user.last_seen_at),
            "sync_ratings_to_trakt": user.sync_ratings_to_trakt,
            "sync_ratings_to_simkl": user.sync_ratings_to_simkl,
            "use_ai_features": user.use_ai_features,
            "is_admin": user.is_admin,
            "privacy_policy_accepted": user.privacy_policy_accepted,
            "privacy_policy_accepted_at": _iso(user.privacy_policy_accepted_at),
            "privacy_policy_version": user.privacy_policy_version,
        },
        "library": [
            {
                "movie": _movie_ref(um.movie),
                "seen": um.seen,
                "elo": um.elo,
                "seeded_elo": um.seeded_elo,
                "battles": um.battles,
                "trakt_rating": um.trakt_rating,
                "last_dueled_at": _iso(um.last_dueled_at),
                "updated_at": _iso(um.updated_at),
            }
            for um in user_movies
        ],
        "duels": [
            {
                "id": str(d.id),
                "created_at": _iso(d.created_at),
                "mode": d.mode,
                "pair_type": d.pair_type,
                "winner": _movie_ref(d.winner_movie),
                "loser": _movie_ref(d.loser_movie),
                "winner_elo_before": d.winner_elo_before,
                "winner_elo_after": d.winner_elo_after,
                "loser_elo_before": d.loser_elo_before,
                "loser_elo_after": d.loser_elo_after,
            }
            for d in duels
        ],
        "tournaments": [
            {
                "id": str(t.id),
                "name": t.name,
                "filter_type": t.filter_type,
                "filter_value": t.filter_value,
                "media_type": t.media_type,
                "bracket_size": t.bracket_size,
                "status": t.status,
                "created_at": _iso(t.created_at),
                "completed_at": _iso(t.completed_at),
                "tagline": t.tagline,
                "theme_description": t.theme_description,
                "is_ai_curated": t.is_ai_curated,
                "llm_response": t.llm_response,
                "champion": _movie_ref(t.champion_movie),
                "matches": [
                    _match(m)
                    for m in sorted(t.matches, key=lambda m: (m.round, m.position))
                ],
            }
            for t in tournaments
        ],
        "suggestions": [
            {
                "id": str(s.id),
                "movie": _movie_ref(s.movie),
                "reason": s.reason,
                "generated_at": _iso(s.generated_at),
                "dismissed_at": _iso(s.dismissed_at),
                "added_to_watchlist_at": _iso(s.added_to_watchlist_at),
            }
            for s in suggestions
        ],
        "swipe_results": [
            {
                "id": str(sr.id),
                "movie": _movie_ref(sr.movie),
                "seen": sr.seen,
                "created_at": _iso(sr.created_at),
            }
            for sr in swipe_results
        ],
        "feedback_reports": [
            {
                "id": str(fr.id),
                "title": fr.title,
                "description": fr.description,
                "created_at": _iso(fr.created_at),
                "has_screenshot": fr.screenshot_data_enc is not None,
            }
            for fr in feedback_reports
        ],
        "pool_expansions": [
            {
                "id": str(pe.id),
                "source": pe.source,
                "source_key": pe.source_key,
                "films_added": pe.films_added,
                "ran_at": _iso(pe.ran_at),
            }
            for pe in pool_expansions
        ],
        "truncated_sections": truncated_sections,
    }


async def _load_capped(db: AsyncSession, stmt) -> tuple[list, bool]:
    """Run ``stmt`` bounded to the cap; the flag reports whether rows were cut."""
    result = await db.execute(stmt.limit(EXPORT_ROW_CAP + 1))
    rows = result.unique().scalars().all()
    return rows[:EXPORT_ROW_CAP], len(rows) > EXPORT_ROW_CAP


async def export_user_data(db: AsyncSession, user: User) -> dict:
    """Load every user-scoped table for ``user`` and build the export payload."""
    uid: uuid.UUID = user.id
    statements = {
        "library": select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .where(UserMovie.user_id == uid)
        .order_by(UserMovie.updated_at, UserMovie.id),
        "duels": select(Duel)
        .options(joinedload(Duel.winner_movie), joinedload(Duel.loser_movie))
        .where(Duel.user_id == uid)
        .order_by(Duel.created_at, Duel.id),
        "tournaments": select(Tournament)
        .options(
            joinedload(Tournament.champion_movie),
            joinedload(Tournament.matches).joinedload(TournamentMatch.movie_a),
            joinedload(Tournament.matches).joinedload(TournamentMatch.movie_b),
            joinedload(Tournament.matches).joinedload(TournamentMatch.winner_movie),
        )
        .where(Tournament.user_id == uid)
        .order_by(Tournament.created_at, Tournament.id),
        "suggestions": select(Suggestion)
        .options(joinedload(Suggestion.movie))
        .where(Suggestion.user_id == uid)
        .order_by(Suggestion.generated_at, Suggestion.id),
        "swipe_results": select(SwipeResult)
        .options(joinedload(SwipeResult.movie))
        .where(SwipeResult.user_id == uid)
        .order_by(SwipeResult.created_at, SwipeResult.id),
        "feedback_reports": select(FeedbackReport)
        .where(FeedbackReport.user_id == uid)
        .order_by(FeedbackReport.created_at, FeedbackReport.id),
        "pool_expansions": select(PoolExpansion)
        .where(PoolExpansion.user_id == uid)
        .order_by(PoolExpansion.ran_at, PoolExpansion.id),
    }

    sections: dict[str, list] = {}
    truncated_sections: list[str] = []
    for name, stmt in statements.items():
        sections[name], truncated = await _load_capped(db, stmt)
        if truncated:
            truncated_sections.append(name)

    return build_export_payload(
        user,
        user_movies=sections["library"],
        duels=sections["duels"],
        tournaments=sections["tournaments"],
        suggestions=sections["suggestions"],
        swipe_results=sections["swipe_results"],
        feedback_reports=sections["feedback_reports"],
        pool_expansions=sections["pool_expansions"],
        truncated_sections=truncated_sections,
        exported_at=datetime.now(timezone.utc),
    )
