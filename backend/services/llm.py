"""Shared LLM client for AI features (uses LiteLLM with Requesty/OpenRouter)."""

import json
import logging

from backend.config import get_settings

logger = logging.getLogger(__name__)


async def chat_completion(
    system: str,
    user_message: str,
    max_tokens: int = 500,
) -> str:
    """Call the LLM via LiteLLM. Returns the text response."""
    settings = get_settings()
    if not settings.LLM_API_KEY:
        raise ValueError(
            "LLM_API_KEY is not configured. "
            "Set it in your environment or .env file to enable AI features."
        )

    # Import here to avoid import-time side effects from litellm
    from litellm import acompletion

    response = await acompletion(
        model=f"openai/{settings.LLM_MODEL}",
        max_tokens=max_tokens,
        api_key=settings.LLM_API_KEY,
        api_base=settings.LLM_BASE_URL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_message},
        ],
    )

    return response.choices[0].message.content


def parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    return json.loads(text)
