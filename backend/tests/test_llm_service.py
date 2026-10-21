"""Tests for the LLM service layer (parse_json_response and chat_completion)."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import asyncio

import pytest

from backend.config import get_settings
from backend.services.llm import (
    LLMBusyError,
    chat_completion,
    parse_json_response,
    reset_llm_slots,
)


# ---------------------------------------------------------------------------
# parse_json_response — plain, fenced, and invalid JSON
# ---------------------------------------------------------------------------


def test_parse_json_response_plain():
    """Plain JSON string is parsed correctly."""
    result = parse_json_response('{"key": "val"}')
    assert result == {"key": "val"}


def test_parse_json_response_markdown_fenced():
    """Markdown-fenced JSON is unwrapped and parsed correctly."""
    result = parse_json_response('```json\n{"key": "val"}\n```')
    assert result == {"key": "val"}


def test_parse_json_response_invalid_raises():
    """Invalid JSON raises json.JSONDecodeError."""
    with pytest.raises(json.JSONDecodeError):
        parse_json_response("not json")


# ---------------------------------------------------------------------------
# chat_completion — missing API key and API error propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_missing_api_key_raises():
    """chat_completion raises ValueError when LLM_API_KEY is empty."""
    mock_settings = MagicMock()
    mock_settings.LLM_API_KEY = ""

    with patch("backend.services.llm.get_settings", return_value=mock_settings):
        with pytest.raises(ValueError, match="LLM_API_KEY is not configured"):
            await chat_completion(system="test", user_message="hello")


@pytest.mark.asyncio
async def test_chat_completion_api_error_propagates():
    """Exceptions from litellm.acompletion propagate (not swallowed)."""
    mock_settings = MagicMock()
    mock_settings.LLM_API_KEY = "test-key"
    mock_settings.LLM_BASE_URL = "https://example.com"
    mock_settings.LLM_MODEL = "test-model"
    mock_settings.LLM_TIMEOUT_SECONDS = 30.0
    mock_settings.LLM_MAX_CONCURRENT = 2

    with patch("backend.services.llm.get_settings", return_value=mock_settings):
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.side_effect = Exception("timeout")
            with pytest.raises(Exception, match="timeout"):
                await chat_completion(system="test", user_message="hello")


# ---------------------------------------------------------------------------
# chat_completion — timeout plumbing and concurrency guard (AUD-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_passes_timeout(monkeypatch):
    captured = {}

    async def fake_acompletion(**kwargs):
        captured.update(kwargs)
        msg = MagicMock()
        msg.message.content = "{}"
        resp = MagicMock()
        resp.choices = [msg]
        resp.usage = None
        return resp

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    monkeypatch.setattr(get_settings(), "LLM_API_KEY", "x")
    await chat_completion("sys", "user")
    assert captured["timeout"] == get_settings().LLM_TIMEOUT_SECONDS
    assert captured["num_retries"] == 0


@pytest.mark.asyncio
async def test_chat_completion_null_content_returns_empty_text(monkeypatch):
    """A reply with no text (content=null) is returned as "" so callers parse it as non-JSON."""

    async def fake_acompletion(**kwargs):
        msg = MagicMock()
        msg.message.content = None
        resp = MagicMock()
        resp.choices = [msg]
        resp.usage = None
        return resp

    monkeypatch.setattr("litellm.acompletion", fake_acompletion)
    monkeypatch.setattr(get_settings(), "LLM_API_KEY", "x")
    assert await chat_completion("sys", "user") == ""


@pytest.mark.asyncio
async def test_chat_completion_fails_fast_when_slots_full(monkeypatch):
    reset_llm_slots()
    monkeypatch.setattr(get_settings(), "LLM_MAX_CONCURRENT", 1)
    monkeypatch.setattr(get_settings(), "LLM_API_KEY", "x")
    gate = asyncio.Event()

    async def slow_acompletion(**kwargs):
        await gate.wait()
        msg = MagicMock()
        msg.message.content = "{}"
        resp = MagicMock()
        resp.choices = [msg]
        resp.usage = None
        return resp

    monkeypatch.setattr("litellm.acompletion", slow_acompletion)
    first = asyncio.create_task(chat_completion("s", "u"))
    await asyncio.sleep(0)  # let `first` take the slot
    with pytest.raises(LLMBusyError):
        await chat_completion("s", "u")  # must not block
    gate.set()
    await first
