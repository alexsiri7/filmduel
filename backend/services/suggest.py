"""AI-powered film suggestion service.

Builds a taste profile from the user's ranked films, selects candidate
unknown films, and asks an LLM to pick 6 personalised recommendations.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from backend.db_models import Movie, UserMovie
from backend.services.llm import chat_completion, parse_json_response

logger = logging.getLogger(__name__)

MIN_RANKED = 20
NUM_PICKS = 6
CANDIDATE_LIMIT = 50


async def _build_taste_profile(
    user_id: uuid.UUID, db: AsyncSession, media_type: str = "movie"
) -> dict | None:
    """Return taste profile dict, or None if the user has < MIN_RANKED films."""
    ranked_stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            UserMovie.battles >= 1,
            UserMovie.elo.isnot(None),
            Movie.media_type == media_type,
        )
        .order_by(UserMovie.elo.desc())
    )
    result = await db.execute(ranked_stmt)
    ranked = result.unique().scalars().all()

    if len(ranked) < MIN_RANKED:
        return None

    top_10 = ranked[:10]
    bottom_5 = ranked[-5:]

    # Genre affinities: avg ELO per genre (only genres with 3+ films)
    genre_elos: dict[str, list[int]] = defaultdict(list)
    for um in ranked:
        if um.movie.genres:
            for g in um.movie.genres:
                genre_elos[g].append(um.elo)

    genre_affinities = {
        g: round(sum(elos) / len(elos))
        for g, elos in genre_elos.items()
        if len(elos) >= 3
    }
    # Sort by avg ELO descending
    genre_affinities = dict(
        sorted(genre_affinities.items(), key=lambda x: x[1], reverse=True)
    )

    def _film_entry(um: UserMovie) -> dict:
        m = um.movie
        return {
            "title": m.title,
            "year": m.year,
            "genres": m.genres or [],
            "elo": um.elo,
        }

    return {
        "top_10": [_film_entry(um) for um in top_10],
        "bottom_5": [_film_entry(um) for um in bottom_5],
        "genre_affinities": genre_affinities,
        "total_ranked": len(ranked),
    }


async def _get_candidates(
    user_id: uuid.UUID, db: AsyncSession, media_type: str = "movie"
) -> list[dict]:
    """Get 40-60 unknown films (seen=NULL) as candidates, preferring ones with posters."""
    stmt = (
        select(UserMovie)
        .options(joinedload(UserMovie.movie))
        .join(UserMovie.movie)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(None),
            Movie.poster_url.isnot(None),
            Movie.media_type == media_type,
        )
        .order_by(
            # By community rating
            Movie.community_rating.desc().nulls_last(),
        )
        .limit(CANDIDATE_LIMIT)
    )
    result = await db.execute(stmt)
    user_movies = result.unique().scalars().all()

    candidates = []
    for um in user_movies:
        m = um.movie
        candidates.append({
            "trakt_id": m.trakt_id,
            "movie_id": str(m.id),
            "title": m.title,
            "year": m.year,
            "genres": m.genres or [],
            "community_rating": float(m.community_rating) if m.community_rating else None,
        })

    return candidates


async def _call_llm(taste_profile: dict, candidates: list[dict]) -> list[dict]:
    """Call LLM to pick 6 films. Returns list of {trakt_id, reason}."""
    system_prompt = (
        "You are a film recommendation assistant for FilmDuel, a movie ranking app. "
        "The user has ranked films via head-to-head duels, producing ELO ratings. "
        "Higher ELO = more preferred. Analyze their taste profile and select exactly "
        f"{NUM_PICKS} films from the candidate list that best match their taste.\n\n"
        "Return ONLY valid JSON in this exact format:\n"
        '{ "picks": [{ "trakt_id": 12345, "reason": "Short personalized reason (1-2 sentences)" }, ...] }\n\n'
        "Rules:\n"
        "- Pick exactly 6 films\n"
        "- Only use trakt_ids from the candidate list\n"
        "- Each reason should reference specific aspects of the user's taste\n"
        "- Aim for variety: don't pick 6 films from the same genre\n"
        "- Prefer films with higher community ratings when taste-fit is similar"
    )

    user_message = (
        f"## User Taste Profile\n\n"
        f"**Top 10 favorites (highest ELO):**\n"
        + "\n".join(
            f"- {f['title']} ({f['year']}) [{', '.join(f['genres'])}] ELO: {f['elo']}"
            for f in taste_profile["top_10"]
        )
        + f"\n\n**Bottom 5 (lowest ELO):**\n"
        + "\n".join(
            f"- {f['title']} ({f['year']}) [{', '.join(f['genres'])}] ELO: {f['elo']}"
            for f in taste_profile["bottom_5"]
        )
        + f"\n\n**Genre affinities (avg ELO):**\n"
        + "\n".join(
            f"- {g}: {elo}" for g, elo in taste_profile["genre_affinities"].items()
        )
        + f"\n\nTotal ranked films: {taste_profile['total_ranked']}"
        + f"\n\n## Candidate Films (pick {NUM_PICKS} from these)\n\n"
        + "\n".join(
            f"- trakt_id={c['trakt_id']}: {c['title']} ({c['year']}) "
            f"[{', '.join(c['genres'])}] "
            f"rating={c['community_rating'] or 'N/A'}"
            for c in candidates
        )
    )

    text_content = await chat_completion(system_prompt, user_message, max_tokens=1500)
    parsed = parse_json_response(text_content)
    return parsed["picks"]


async def generate_suggestions(
    user_id: uuid.UUID, db: AsyncSession, media_type: str = "movie"
) -> list[dict]:
    """Generate 6 personalized film suggestions.

    Returns list of {movie_id: str, reason: str}.
    Raises ValueError if LLM_API_KEY is not set.
    Returns empty list if user has < MIN_RANKED films (caller should check taste_profile).
    """
    taste_profile = await _build_taste_profile(user_id, db, media_type)
    if taste_profile is None:
        logger.info("suggest_skip user_id=%s reason=insufficient_ranked (need %d)", user_id, MIN_RANKED)
        return []

    top_genre = next(iter(taste_profile["genre_affinities"]), None)
    logger.info(
        "suggest_taste_profile user_id=%s num_ranked=%d top_genre=%s",
        user_id, taste_profile["total_ranked"], top_genre,
    )

    candidates = await _get_candidates(user_id, db, media_type)
    logger.info("suggest_candidates user_id=%s candidate_count=%d", user_id, len(candidates))


    if len(candidates) < NUM_PICKS:
        logger.warning(
            "User %s has only %d candidate films, need at least %d",
            user_id, len(candidates), NUM_PICKS,
        )
        return []

    # Build trakt_id -> movie_id lookup
    trakt_to_movie = {c["trakt_id"]: c["movie_id"] for c in candidates}

    picks = await _call_llm(taste_profile, candidates)
    logger.info("suggest_llm_response user_id=%s picks_returned=%d", user_id, len(picks))

    # Validate and map picks
    results = []
    for pick in picks:
        trakt_id = pick.get("trakt_id")
        reason = pick.get("reason", "Recommended for you.")
        if trakt_id in trakt_to_movie:
            results.append({
                "movie_id": trakt_to_movie[trakt_id],
                "reason": reason,
            })
        if len(results) >= NUM_PICKS:
            break

    return results


async def has_enough_ranked(user_id: uuid.UUID, db: AsyncSession, media_type: str = "movie") -> bool:
    """Check if user has at least MIN_RANKED ranked films of the given type."""
    count_stmt = (
        select(func.count())
        .select_from(UserMovie)
        .join(Movie, UserMovie.movie_id == Movie.id)
        .where(
            UserMovie.user_id == user_id,
            UserMovie.seen.is_(True),
            UserMovie.battles >= 1,
            UserMovie.elo.isnot(None),
            Movie.media_type == media_type,
        )
    )
    result = await db.execute(count_stmt)
    count = result.scalar() or 0
    return count >= MIN_RANKED
