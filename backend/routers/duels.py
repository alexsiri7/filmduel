"""Duel submission routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.db import get_supabase
from backend.models import DuelSubmit, DuelResult
from backend.routers.auth import get_current_user_id
from backend.services.elo import outcome_to_scores, update_elo

router = APIRouter(prefix="/api/duels", tags=["duels"])

DEFAULT_ELO = 1500.0


@router.post("/submit", response_model=DuelResult)
async def submit_duel(
    body: DuelSubmit,
    user_id: str = Depends(get_current_user_id),
):
    """Submit the result of a duel and update ELO ratings."""
    db = get_supabase()

    # Fetch the pending duel
    duel_result = db.table("duels").select("*").eq("id", body.duel_id).execute()
    if not duel_result.data:
        raise HTTPException(status_code=404, detail="Duel not found")

    duel = duel_result.data[0]
    if duel["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Not your duel")
    if duel["status"] != "pending":
        raise HTTPException(status_code=400, detail="Duel already completed")

    movie_a_id = duel["movie_a_id"]
    movie_b_id = duel["movie_b_id"]
    outcome = body.outcome.value

    # Get current ELO ratings (or default)
    rating_a_row = (
        db.table("rankings")
        .select("elo_rating")
        .eq("user_id", user_id)
        .eq("movie_id", movie_a_id)
        .execute()
    )
    rating_b_row = (
        db.table("rankings")
        .select("elo_rating")
        .eq("user_id", user_id)
        .eq("movie_id", movie_b_id)
        .execute()
    )

    old_elo_a = rating_a_row.data[0]["elo_rating"] if rating_a_row.data else DEFAULT_ELO
    old_elo_b = rating_b_row.data[0]["elo_rating"] if rating_b_row.data else DEFAULT_ELO

    # Calculate new ELO
    score_a, score_b = outcome_to_scores(outcome)
    if outcome == "neither":
        # Both disliked — no ELO change
        new_elo_a, new_elo_b = old_elo_a, old_elo_b
    else:
        new_elo_a, new_elo_b = update_elo(old_elo_a, old_elo_b, score_a)

    delta_a = round(new_elo_a - old_elo_a, 2)
    delta_b = round(new_elo_b - old_elo_b, 2)

    # Upsert rankings
    for movie_id, new_elo in [(movie_a_id, new_elo_a), (movie_b_id, new_elo_b)]:
        existing = (
            db.table("rankings")
            .select("id, duel_count, win_count")
            .eq("user_id", user_id)
            .eq("movie_id", movie_id)
            .execute()
        )
        is_winner = (movie_id == movie_a_id and score_a == 1.0) or (
            movie_id == movie_b_id and score_b == 1.0
        )
        if existing.data:
            row = existing.data[0]
            db.table("rankings").update(
                {
                    "elo_rating": new_elo,
                    "duel_count": row["duel_count"] + 1,
                    "win_count": row["win_count"] + (1 if is_winner else 0),
                }
            ).eq("id", row["id"]).execute()
        else:
            db.table("rankings").insert(
                {
                    "user_id": user_id,
                    "movie_id": movie_id,
                    "elo_rating": new_elo,
                    "duel_count": 1,
                    "win_count": 1 if is_winner else 0,
                }
            ).execute()

    # Mark duel as completed
    db.table("duels").update(
        {"status": "completed", "outcome": outcome}
    ).eq("id", body.duel_id).execute()

    return DuelResult(
        duel_id=body.duel_id,
        outcome=body.outcome,
        movie_a_elo_delta=delta_a,
        movie_b_elo_delta=delta_b,
    )
