"""LLM-powered film curator for AI-curated tournaments."""

from __future__ import annotations

import json
import logging

import httpx
from fastapi import HTTPException

from backend.config import get_settings

logger = logging.getLogger(__name__)

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

Candidate films:
{candidates_text}
"""


async def curate_tournament(
    candidates: list[dict],
    bracket_size: int,
    filter_context: str = "",
) -> dict:
    """Call Claude to select films and generate a theme.

    Args:
        candidates: List of dicts with keys: id, title, year, genres, elo, battles
        bracket_size: Number of films to select
        filter_context: Optional description of active filters (e.g. "Genre: Horror")

    Returns:
        Dict with keys: name, tagline, theme_description, film_ids

    Raises:
        HTTPException on API or parsing errors.
    """
    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="AI curation is not configured (missing ANTHROPIC_API_KEY)",
        )

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
        candidates_text=candidates_text,
    )

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 500,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_prompt}],
                },
            )
    except httpx.TimeoutException:
        logger.error("Anthropic API timeout during tournament curation")
        raise HTTPException(
            status_code=500,
            detail="AI curation timed out. Please try again.",
        )
    except httpx.HTTPError as exc:
        logger.error("Anthropic API request failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="AI curation request failed. Please try again.",
        )

    if resp.status_code != 200:
        logger.error(
            "Anthropic API returned %d: %s", resp.status_code, resp.text[:500]
        )
        raise HTTPException(
            status_code=500,
            detail=f"AI curation failed (API status {resp.status_code})",
        )

    # Extract text content from response
    try:
        api_response = resp.json()
        text_content = ""
        for block in api_response.get("content", []):
            if block.get("type") == "text":
                text_content += block["text"]
    except (ValueError, KeyError) as exc:
        logger.error("Failed to parse Anthropic API response structure: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="AI curation returned an unexpected response format",
        )

    # Parse the JSON from the LLM output
    try:
        result = json.loads(text_content.strip())
    except json.JSONDecodeError:
        # Try extracting JSON from markdown code block
        import re

        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text_content, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1))
            except json.JSONDecodeError:
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
