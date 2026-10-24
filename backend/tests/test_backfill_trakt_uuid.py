"""Tests for backend/scripts/backfill_trakt_uuid.py (_resolve_uuid and main)."""

from __future__ import annotations

import logging
import types
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.scripts.backfill_trakt_uuid import _resolve_uuid, main


def _session_factory(session):
    @asynccontextmanager
    async def factory():
        yield session

    return factory


# ---------------------------------------------------------------------------
# _resolve_uuid
# ---------------------------------------------------------------------------


class TestResolveUuid:
    @pytest.mark.asyncio
    async def test_returns_uuid_as_str_when_profile_succeeds_on_first_call(self):
        user = types.SimpleNamespace(
            trakt_access_token="old-token",
            trakt_refresh_token="refresh-tok",
            trakt_refresh_token_enc="enc",
        )
        settings = MagicMock()

        with patch("backend.scripts.backfill_trakt_uuid.TraktClient") as TraktClient:
            TraktClient.return_value.get_profile = AsyncMock(
                return_value={"user": {"ids": {"uuid": 12345}}}
            )
            TraktClient.return_value.refresh_token = AsyncMock()

            result = await _resolve_uuid(user, settings)

        assert result == "12345"
        assert isinstance(result, str)
        TraktClient.return_value.refresh_token.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refreshes_token_and_resolves_uuid_when_first_profile_call_fails(self):
        user = types.SimpleNamespace(
            trakt_access_token="old-token",
            trakt_refresh_token="refresh-tok",
            trakt_refresh_token_enc="enc",
        )
        settings = MagicMock()

        with patch("backend.scripts.backfill_trakt_uuid.TraktClient") as TraktClient:
            TraktClient.return_value.get_profile = AsyncMock(
                side_effect=[
                    httpx.HTTPError("boom"),
                    {"user": {"ids": {"uuid": "uuid-after-refresh"}}},
                ]
            )
            TraktClient.return_value.refresh_token = AsyncMock(
                return_value={"access_token": "new-access-token"}
            )

            result = await _resolve_uuid(user, settings)

        assert result == "uuid-after-refresh"
        TraktClient.return_value.refresh_token.assert_awaited_once_with(
            user.trakt_refresh_token,
            client_secret=settings.TRAKT_CLIENT_SECRET,
            redirect_uri=settings.TRAKT_REDIRECT_URI,
        )
        assert user.trakt_access_token == "new-access-token"
        # refresh_token response had no "refresh_token" key, so the fallback
        # should keep the user's existing refresh token unchanged.
        assert user.trakt_refresh_token == "refresh-tok"

        last_call_kwargs = TraktClient.call_args_list[-1].kwargs
        assert last_call_kwargs["access_token"] == "new-access-token"

    @pytest.mark.asyncio
    async def test_returns_none_when_profile_fails_and_no_refresh_token(self):
        user = types.SimpleNamespace(
            trakt_access_token="old-token",
            trakt_refresh_token="refresh-tok",
            trakt_refresh_token_enc=None,
        )
        settings = MagicMock()

        with patch("backend.scripts.backfill_trakt_uuid.TraktClient") as TraktClient:
            TraktClient.return_value.get_profile = AsyncMock(side_effect=httpx.HTTPError("boom"))
            TraktClient.return_value.refresh_token = AsyncMock()

            result = await _resolve_uuid(user, settings)

        assert result is None
        TraktClient.return_value.refresh_token.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_none_when_profile_fails_and_refresh_also_fails(self):
        user = types.SimpleNamespace(
            trakt_access_token="old-token",
            trakt_refresh_token="refresh-tok",
            trakt_refresh_token_enc="enc",
        )
        settings = MagicMock()

        with patch("backend.scripts.backfill_trakt_uuid.TraktClient") as TraktClient:
            TraktClient.return_value.get_profile = AsyncMock(side_effect=httpx.HTTPError("boom"))
            TraktClient.return_value.refresh_token = AsyncMock(
                side_effect=httpx.HTTPError("refresh failed")
            )

            result = await _resolve_uuid(user, settings)

        assert result is None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


class TestMain:
    @pytest.mark.asyncio
    async def test_classifies_rows_into_resolved_cleared_and_skipped(self, caplog):
        row1 = types.SimpleNamespace(
            trakt_user_id="user-1", trakt_uuid=None, trakt_access_token_enc=None
        )
        row2 = types.SimpleNamespace(
            trakt_user_id="user-2", trakt_uuid=None, trakt_access_token_enc="enc"
        )
        row3 = types.SimpleNamespace(
            trakt_user_id="user-3", trakt_uuid=None, trakt_access_token_enc="enc"
        )
        row4 = types.SimpleNamespace(
            trakt_user_id="user-4", trakt_uuid=None, trakt_access_token_enc="enc"
        )

        db = AsyncMock()
        db.execute.return_value = MagicMock()
        db.execute.return_value.scalars.return_value.all.return_value = [row1, row2, row3, row4]

        with (
            patch("backend.scripts.backfill_trakt_uuid.get_settings", return_value=MagicMock()),
            patch(
                "backend.scripts.backfill_trakt_uuid.async_session_factory",
                _session_factory(db),
            ),
            patch(
                "backend.scripts.backfill_trakt_uuid._resolve_uuid",
                new=AsyncMock(
                    side_effect=["uuid-2", None, RuntimeError("undecryptable")]
                ),
            ) as resolve_uuid,
            caplog.at_level(logging.INFO, logger="backfill_trakt_uuid"),
        ):
            await main()

        assert row1.trakt_user_id is None
        assert row1.trakt_uuid is None

        assert row2.trakt_uuid == "uuid-2"
        assert row2.trakt_user_id == "user-2"

        assert row3.trakt_user_id is None
        assert row3.trakt_uuid is None

        assert row4.trakt_user_id is None
        assert row4.trakt_uuid is None

        assert resolve_uuid.await_count == 3
        # row1 hits `continue` before reaching `await db.flush()`, so flush
        # only runs for rows 2-4 (3 times), not once per row overall.
        assert db.flush.await_count == 3
        db.commit.assert_awaited_once()
        assert "resolved=1 cleared=3" in caplog.text
