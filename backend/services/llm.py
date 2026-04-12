"""Shared LLM client for AI features (uses LiteLLM with Requesty/OpenRouter)."""

import json
import logging
import time

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

    model_name = f"openai/{settings.LLM_MODEL}"
    logger.info("llm_request model=%s max_tokens=%d", model_name, max_tokens)

    t0 = time.monotonic()
    try:
        response = await acompletion(
            model=model_name,
            max_tokens=max_tokens,
            api_key=settings.LLM_API_KEY,
            api_base=settings.LLM_BASE_URL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        )
    except Exception:
        elapsed = time.monotonic() - t0
        logger.error("llm_error model=%s elapsed=%.2fs", model_name, elapsed)
        raise

    elapsed = time.monotonic() - t0
    usage = getattr(response, "usage", None)
    total_tokens = usage.total_tokens if usage else None
    logger.info("llm_response model=%s elapsed=%.2fs tokens=%s", model_name, elapsed, total_tokens)

    return response.choices[0].message.content


def parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1]) if lines[-1].strip() == "```" else "\n".join(lines[1:])
    return json.loads(text)
