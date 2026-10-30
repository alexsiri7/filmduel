"""Shared LLM client for AI features.

Calls an OpenAI-compatible chat-completions endpoint (Requesty/OpenRouter) over httpx.
"""

import asyncio
import json
import logging
import time

import httpx

from backend.config import get_settings

logger = logging.getLogger(__name__)


class LLMBusyError(Exception):
    """Raised when LLM_MAX_CONCURRENT calls are already in flight (AUD-01).

    Callers must map this to HTTP 503 and must not retry inside the same
    request: the whole point is to release the pooled DB connection quickly.
    """


class LLMResponseError(Exception):
    """The provider replied, but not with a readable chat completion."""


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
    """Call the configured chat-completions endpoint. Returns the text response."""
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
        model_name = settings.LLM_MODEL
        url = settings.LLM_BASE_URL.rstrip("/") + "/chat/completions"
        logger.info("llm_request model=%s max_tokens=%d", model_name, max_tokens)

        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=settings.LLM_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
                    json={
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user_message},
                        ],
                        "max_tokens": max_tokens,
                    },
                )
            response.raise_for_status()
        except Exception:
            logger.error(
                "llm_error model=%s elapsed=%.2fs", model_name, time.monotonic() - t0
            )
            raise

        try:
            data = response.json()
            content = data["choices"][0]["message"].get("content")
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
            # Callers read ValueError as "LLM_API_KEY not configured", so an
            # unreadable reply (json.JSONDecodeError is a ValueError) must not be one.
            logger.error(
                "llm_error model=%s elapsed=%.2fs", model_name, time.monotonic() - t0
            )
            raise LLMResponseError("LLM reply was not a chat completion") from exc

        elapsed = time.monotonic() - t0
        usage = data.get("usage")
        total_tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        logger.info(
            "llm_response model=%s elapsed=%.2fs tokens=%s",
            model_name,
            elapsed,
            total_tokens,
        )

        # content is null when the model replies with no text.
        return content or ""


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
