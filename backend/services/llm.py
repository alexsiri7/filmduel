"""Shared LLM client for AI features (uses OpenRouter/Requesty API)."""

import json
import logging

import httpx
from backend.config import get_settings

logger = logging.getLogger(__name__)


async def chat_completion(
    system: str,
    user_message: str,
    max_tokens: int = 500,
) -> str:
    """Call the LLM via OpenRouter-compatible API. Returns the text response."""
    settings = get_settings()
    if not settings.LLM_API_KEY:
        raise ValueError(
            "LLM_API_KEY is not configured. "
            "Set it in your environment or .env file to enable AI features."
        )

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.LLM_MODEL,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
            },
        )
        resp.raise_for_status()

    data = resp.json()
    return data["choices"][0]["message"]["content"]


def parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    return json.loads(text)
