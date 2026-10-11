"""Shared LLM client for AI features (uses LiteLLM with Requesty/OpenRouter)."""

import asyncio
import json
import logging
import time

from backend.config import get_settings

logger = logging.getLogger(__name__)


class LLMBusyError(Exception):
    """Raised when LLM_MAX_CONCURRENT calls are already in flight (AUD-01).

    Callers must map this to HTTP 503 and must not retry inside the same
    request: the whole point is to release the pooled DB connection quickly.
    """


_llm_slots: asyncio.Semaphore | None = None


def _slots() -> asyncio.Semaphore:
    # Lazily created so the semaphore binds to the running loop, and so tests
    # can reset it via reset_llm_slots().
    global _llm_slots
    if _llm_slots is None:
        _llm_slots = asyncio.Semaphore(get_settings().LLM_MAX_CONCURRENT)
    return _llm_slots


def reset_llm_slots() -> None:
    """Test hook: drop the semaphore so the next call rebuilds it from settings."""
    global _llm_slots
    _llm_slots = None


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

    slots = _slots()
    if slots.locked():
        # Fail fast: do not await acquire(), which would park this request while
        # it still holds a pooled DB connection.
        logger.warning("llm_busy max_concurrent=%d", settings.LLM_MAX_CONCURRENT)
        raise LLMBusyError("AI features are busy. Please try again in a moment.")

    async with slots:
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
                timeout=settings.LLM_TIMEOUT_SECONDS,
                num_retries=0,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_message},
                ],
            )
        except Exception:
            logger.error(
                "llm_error model=%s elapsed=%.2fs", model_name, time.monotonic() - t0
            )
            raise

        elapsed = time.monotonic() - t0
        usage = getattr(response, "usage", None)
        total_tokens = usage.total_tokens if usage else None
        logger.info(
            "llm_response model=%s elapsed=%.2fs tokens=%s",
            model_name,
            elapsed,
            total_tokens,
        )

        return response.choices[0].message.content


def parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
        else:
            text = "\n".join(lines[1:])
    return json.loads(text)
