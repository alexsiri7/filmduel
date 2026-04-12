"""LLM-powered film curator for AI-curated tournaments."""

from __future__ import annotations

import logging
import re

from fastapi import HTTPException

from backend.services.llm import chat_completion, parse_json_response

logger = logging.getLogger(__name__)


def _sanitize_theme_hint(hint: str) -> str:
    """Strip potential prompt injection from user theme hints."""
    hint = hint[:100]  # max length
    hint = re.sub(r'[{}\[\]<>]', '', hint)  # remove structural chars
    return hint.strip()

SYSTEM_PROMPT = """\
You are a film curator for a movie ranking app. Given a list of candidate films \
(with titles, years, genres, and user ELO ratings), select exactly {bracket_size} \
films that form a compelling, thematic tournament bracket.

Rules:
- Select ONLY from the candidate list (use the exact IDs provided)
- The theme should be specific and non-obvious — not just a genre
- Mix different ELO tiers for interesting matchups
- The theme should connect the films in a surprising or insightful way

Return ONLY valid JSON with no markdown formatting:
{{"name": "bracket name", "tagline": "short punchy tagline", "theme_description": "2-3 sentence description of the theme and why these films were chosen", "film_ids": ["id1", "id2", ...]}}
"""

USER_PROMPT_TEMPLATE = """\
Bracket size: {bracket_size}
{filter_context}
{theme_hint}
Candidate films:
{candidates_text}
"""


async def curate_tournament(
    candidates: list[dict],
    bracket_size: int,
    filter_context: str = "",
    theme_hint: str = "",
) -> dict:
    """Call LLM to select films and generate a theme.

    Args:
        candidates: List of dicts with keys: id, title, year, genres, elo, battles
        bracket_size: Number of films to select
        filter_context: Optional description of active filters (e.g. "Genre: Horror")

    Returns:
        Dict with keys: name, tagline, theme_description, film_ids

    Raises:
        HTTPException on API or parsing errors.
    """
    # Build candidate text
    lines = []
    for c in candidates:
        genres_str = ", ".join(c.get("genres") or []) or "unknown"
        lines.append(
            f'- ID: {c["id"]} | "{c["title"]}" ({c.get("year", "?")})'
            f" | Genres: {genres_str} | ELO: {c.get('elo', '?')}"
            f" | Battles: {c.get('battles', 0)}"
        )
    candidates_text = "\n".join(lines)

    system_prompt = SYSTEM_PROMPT.format(bracket_size=bracket_size)
    user_prompt = USER_PROMPT_TEMPLATE.format(
        bracket_size=bracket_size,
        filter_context=f"Active filter: {filter_context}" if filter_context else "No filter applied",
        theme_hint=f'User theme (use as inspiration): "{_sanitize_theme_hint(theme_hint)}"' if theme_hint else "",
        candidates_text=candidates_text,
    )

    try:
        text_content = await chat_completion(system_prompt, user_prompt, max_tokens=2000)
    except ValueError as exc:
        # LLM_API_KEY not configured
        raise HTTPException(
            status_code=500,
            detail=f"AI curation is not configured ({exc})",
        )
    except Exception as exc:
        logger.error("LLM request failed during tournament curation: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="AI curation request failed. Please try again.",
        )

    # Parse the JSON from the LLM output
    try:
        result = parse_json_response(text_content)
    except Exception:
        # Try extracting JSON from markdown code block as fallback
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text_content, re.DOTALL)
        if match:
            try:
                import json
                result = json.loads(match.group(1))
            except Exception:
                logger.error("Failed to parse LLM JSON output: %s", text_content[:500])
                raise HTTPException(
                    status_code=500,
                    detail="AI curation returned invalid JSON. Please try again.",
                )
        else:
            logger.error("Failed to parse LLM JSON output: %s", text_content[:500])
            raise HTTPException(
                status_code=500,
                detail="AI curation returned invalid JSON. Please try again.",
            )

    # Validate required fields
    required_keys = {"name", "tagline", "theme_description", "film_ids"}
    missing = required_keys - set(result.keys())
    if missing:
        logger.error("LLM response missing keys %s: %s", missing, result)
        raise HTTPException(
            status_code=500,
            detail=f"AI curation response missing fields: {', '.join(missing)}",
        )

    if not isinstance(result["film_ids"], list):
        raise HTTPException(
            status_code=500,
            detail="AI curation returned invalid film_ids (expected list)",
        )

    if len(result["film_ids"]) != bracket_size:
        logger.warning(
            "LLM returned %d films instead of %d, trimming/padding",
            len(result["film_ids"]),
            bracket_size,
        )
        # Trim if too many, but if too few that's an error
        if len(result["film_ids"]) > bracket_size:
            result["film_ids"] = result["film_ids"][:bracket_size]
        else:
            raise HTTPException(
                status_code=500,
                detail=f"AI selected {len(result['film_ids'])} films but bracket needs {bracket_size}. Please try again.",
            )

    return result
