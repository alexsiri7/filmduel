"""Tests for the LLM service layer (parse_json_response and chat_completion)."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import pytest

from backend.services.llm import chat_completion, parse_json_response


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

    with patch("backend.services.llm.get_settings", return_value=mock_settings):
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_acompletion:
            mock_acompletion.side_effect = Exception("timeout")
            with pytest.raises(Exception, match="timeout"):
                await chat_completion(system="test", user_message="hello")
