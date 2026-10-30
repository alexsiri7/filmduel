"""Tests for the LLM service layer (parse_json_response and chat_completion)."""

from __future__ import annotations

import functools
import json
import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("TOKEN_ENC_KEY", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

import asyncio

import httpx
import pytest

from backend.config import get_settings
from backend.services.llm import (
    LLMBusyError,
    LLMResponseError,
    chat_completion,
    parse_json_response,
    reset_llm_slots,
)


def _completion(content: str | None = "{}") -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _route_llm(monkeypatch, handler) -> list[httpx.Request]:
    """Route every AsyncClient through a MockTransport and record its requests."""
    requests: list[httpx.Request] = []

    async def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        response = handler(request)
        if asyncio.iscoroutine(response):
            response = await response
        return response

    transport = httpx.MockTransport(recording)
    monkeypatch.setattr(
        "httpx.AsyncClient", functools.partial(httpx.AsyncClient, transport=transport)
    )
    return requests


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


def _refuse_connection(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("timeout")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler, expected",
    [
        (_refuse_connection, httpx.ConnectError),
        (lambda request: httpx.Response(500, json={"error": "boom"}), httpx.HTTPStatusError),
    ],
    ids=["transport", "http-status"],
)
async def test_chat_completion_api_error_propagates(monkeypatch, handler, expected):
    """Transport and HTTP errors propagate, and never as the "not configured" ValueError."""
    monkeypatch.setattr(get_settings(), "LLM_API_KEY", "x")
    _route_llm(monkeypatch, handler)
    with pytest.raises(expected) as excinfo:
        await chat_completion(system="test", user_message="hello")
    assert not isinstance(excinfo.value, ValueError)


@pytest.mark.asyncio
async def test_chat_completion_wire_request(monkeypatch):
    """One POST to {LLM_BASE_URL}/chat/completions with bearer auth and the bare model name."""
    settings = get_settings()
    monkeypatch.setattr(settings, "LLM_API_KEY", "k")
    monkeypatch.setattr(settings, "LLM_BASE_URL", "https://router.example/v1/")
    monkeypatch.setattr(settings, "LLM_MODEL", "google/x")
    requests = _route_llm(monkeypatch, lambda request: httpx.Response(200, json=_completion("hi")))

    assert await chat_completion("S", "U", max_tokens=123) == "hi"

    [request] = requests
    assert request.method == "POST"
    assert str(request.url) == "https://router.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer k"
    assert json.loads(request.content) == {
        "model": "google/x",
        "messages": [
            {"role": "system", "content": "S"},
            {"role": "user", "content": "U"},
        ],
        "max_tokens": 123,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [b"not json", b"{}", b'{"choices": []}'])
async def test_chat_completion_unreadable_reply_is_not_value_error(monkeypatch, body):
    """Callers read ValueError as "not configured"; an unreadable reply must not look like one."""
    monkeypatch.setattr(get_settings(), "LLM_API_KEY", "x")
    _route_llm(monkeypatch, lambda request: httpx.Response(200, content=body))
    with pytest.raises(LLMResponseError) as excinfo:
        await chat_completion("sys", "user")
    assert not isinstance(excinfo.value, ValueError)


# ---------------------------------------------------------------------------
# chat_completion — timeout plumbing and concurrency guard (AUD-01)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_completion_passes_timeout(monkeypatch):
    monkeypatch.setattr(get_settings(), "LLM_API_KEY", "x")
    requests = _route_llm(monkeypatch, lambda request: httpx.Response(200, json=_completion()))
    await chat_completion("sys", "user")
    [request] = requests  # no retries
    timeout = get_settings().LLM_TIMEOUT_SECONDS
    assert request.extensions["timeout"] == {
        "connect": timeout,
        "read": timeout,
        "write": timeout,
        "pool": timeout,
    }


@pytest.mark.asyncio
async def test_chat_completion_null_content_returns_empty_text(monkeypatch):
    """A reply with no text (content=null) is returned as "" so callers parse it as non-JSON."""
    monkeypatch.setattr(get_settings(), "LLM_API_KEY", "x")
    _route_llm(monkeypatch, lambda request: httpx.Response(200, json=_completion(None)))
    assert await chat_completion("sys", "user") == ""


@pytest.mark.asyncio
async def test_chat_completion_fails_fast_when_slots_full(monkeypatch):
    reset_llm_slots()
    monkeypatch.setattr(get_settings(), "LLM_MAX_CONCURRENT", 1)
    monkeypatch.setattr(get_settings(), "LLM_API_KEY", "x")
    gate = asyncio.Event()

    async def slow_reply(request: httpx.Request) -> httpx.Response:
        await gate.wait()
        return httpx.Response(200, json=_completion())

    _route_llm(monkeypatch, slow_reply)
    first = asyncio.create_task(chat_completion("s", "u"))
    await asyncio.sleep(0)  # let `first` take the slot
    with pytest.raises(LLMBusyError):
        await chat_completion("s", "u")  # must not block
    gate.set()
    await first
