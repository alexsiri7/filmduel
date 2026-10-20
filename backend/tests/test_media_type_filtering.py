"""Tests for media_type filtering across backend services.

Verifies that rankings, suggestions, and sync services correctly
pass and use the media_type parameter.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.sync import _rate_with_retry


def _rating_rows(*rows):
    """get_elo_ratings result rows as (elo, below, equal, n)."""
    return [SimpleNamespace(elo=e, below=b, equal=q, n=n) for e, b, q, n in rows]


# ---------------------------------------------------------------------------
# _rate_with_retry — media_type dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_with_retry_dispatches_to_movie():
    """Default media_type='movie' calls rate with media_type='movie'."""
    client = AsyncMock()
    await _rate_with_retry(client, item_id=123, rating=8, media_type="movie")
    client.rate.assert_awaited_once_with(123, 8, media_type="movie")


@pytest.mark.asyncio
async def test_rate_with_retry_dispatches_to_show():
    """media_type='show' calls rate with media_type='show'."""
    client = AsyncMock()
    await _rate_with_retry(client, item_id=456, rating=7, media_type="show")
    client.rate.assert_awaited_once_with(456, 7, media_type="show")


# ---------------------------------------------------------------------------
# get_user_rankings — media_type parameter propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rankings_passes_media_type():
    """get_user_rankings builds a query that includes Movie.media_type filter."""
    from backend.services.rankings import get_user_rankings

    uid = uuid.uuid4()

    # Mock db to return empty results
    mock_result = MagicMock()
    mock_result.unique.return_value.scalars.return_value.all.return_value = []
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 0

    db = AsyncMock()
    db.execute.side_effect = [mock_result, mock_count_result]

    rankings, total = await get_user_rankings(db, uid, media_type="show")

    assert total == 0
    assert rankings == []
    # Verify execute was called twice (main query + count query)
    assert db.execute.await_count == 2


# ---------------------------------------------------------------------------
# has_enough_ranked — media_type propagation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_has_enough_ranked_passes_media_type():
    """has_enough_ranked filters by media_type."""
    from backend.services.suggest import has_enough_ranked

    uid = uuid.uuid4()
    mock_result = MagicMock()
    mock_result.scalar.return_value = 0

    db = AsyncMock()
    db.execute.return_value = mock_result

    result = await has_enough_ranked(uid, db, media_type="show")
    assert result is False
    db.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# sync_ratings_background — error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def testsync_ratings_background_handles_exceptions():
    """sync_ratings_background logs exceptions instead of crashing."""
    from backend.services.sync import sync_ratings_background

    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    with patch("backend.services.sync.async_session_factory") as mock_factory:
        mock_factory.return_value.__aenter__ = AsyncMock(
            side_effect=RuntimeError("DB down")
        )
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        # Should not raise — error is caught and logged
        await sync_ratings_background(uid, mid_a, 1100, mid_b, 900)


@pytest.mark.asyncio
async def testsync_ratings_background_refreshes_expired_token():
    """sync_ratings_background calls ensure_fresh_token before syncing."""
    from backend.services.sync import sync_ratings_background

    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()
    trakt_id_a = 173916
    trakt_id_b = 200000

    mock_user = MagicMock()
    mock_user.sync_ratings_to_simkl = False
    mock_user.trakt_access_token = "expired-token"

    mock_rows = [
        MagicMock(id=mid_a, trakt_id=trakt_id_a, simkl_id=None, media_type="movie"),
        MagicMock(id=mid_b, trakt_id=trakt_id_b, simkl_id=None, media_type="movie"),
    ]

    with (
        patch("backend.services.sync.async_session_factory") as mock_factory,
        patch(
            "backend.services.sync.ensure_fresh_token", new_callable=AsyncMock
        ) as mock_refresh,
        patch(
            "backend.services.sync.sync_post_duel", new_callable=AsyncMock
        ) as mock_sync,
        patch(
            "backend.services.sync.trakt_token_needs_refresh", return_value=True
        ),
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_user_refreshed = MagicMock()
        mock_user_refreshed.trakt_access_token = "fresh-token"
        mock_refresh.return_value = mock_user_refreshed

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user
        mock_locked_user_result = MagicMock()
        mock_locked_user_result.scalar_one.return_value = mock_user
        mock_movies_result = MagicMock()
        mock_movies_result.all.return_value = mock_rows
        mock_elos_result = MagicMock()
        mock_elos_result.all.return_value = _rating_rows((900, 0, 1, 2), (1100, 1, 1, 2))
        mock_session.execute.side_effect = [
            mock_user_result,
            mock_locked_user_result,
            mock_movies_result,
            mock_elos_result,
        ]

        await sync_ratings_background(uid, mid_a, 1100, mid_b, 900)

        mock_refresh.assert_awaited_once_with(mock_user, mock_session)
        mock_session.commit.assert_awaited_once()
        mock_sync.assert_awaited_once()
        call_args = mock_sync.call_args
        assert call_args[0][0] == "fresh-token"
        assert set(call_args[0][1]) == {(trakt_id_a, 1100), (trakt_id_b, 900)}
        assert call_args[0][2] == {900: 3, 1100: 8}
        assert call_args[0][3] == "movie"


@pytest.mark.asyncio
async def testsync_ratings_background_skips_if_user_not_found():
    """sync_ratings_background returns early when user record is missing."""
    from backend.services.sync import sync_ratings_background

    with (
        patch("backend.services.sync.async_session_factory") as mock_factory,
        patch(
            "backend.services.sync.ensure_fresh_token", new_callable=AsyncMock
        ) as mock_refresh,
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = None
        mock_session.execute.return_value = mock_exec_result

        await sync_ratings_background(
            uuid.uuid4(), uuid.uuid4(), 1100, uuid.uuid4(), 900
        )

        mock_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def testsync_ratings_background_skips_if_no_trakt_token():
    """sync_ratings_background returns early when user has no Trakt token linked."""
    from backend.services.sync import sync_ratings_background

    mock_user = MagicMock()
    mock_user.sync_ratings_to_simkl = False
    mock_user.trakt_access_token = None

    with (
        patch("backend.services.sync.async_session_factory") as mock_factory,
        patch(
            "backend.services.sync.ensure_fresh_token", new_callable=AsyncMock
        ) as mock_refresh,
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_exec_result

        await sync_ratings_background(
            uuid.uuid4(), uuid.uuid4(), 1100, uuid.uuid4(), 900
        )

        mock_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def testsync_ratings_background_refresh_failure_is_swallowed():
    """sync_ratings_background swallows exceptions from ensure_fresh_token."""
    import httpx
    from backend.services.sync import sync_ratings_background

    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    mock_user = MagicMock()
    mock_user.sync_ratings_to_simkl = False
    mock_user.trakt_access_token = "expired-token"

    with (
        patch("backend.services.sync.async_session_factory") as mock_factory,
        patch(
            "backend.services.sync.ensure_fresh_token",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPStatusError(
                "401", request=MagicMock(), response=MagicMock(status_code=401)
            ),
        ),
        patch(
            "backend.services.sync.sync_post_duel", new_callable=AsyncMock
        ) as mock_sync,
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_exec_result

        await sync_ratings_background(uid, mid_a, 1100, mid_b, 900)

        mock_sync.assert_not_awaited()


@pytest.mark.asyncio
async def testsync_ratings_background_skips_when_opt_out():
    """sync_ratings_background pushes nothing when every provider's sync is off."""
    from backend.services.sync import sync_ratings_background

    mock_user = MagicMock()
    mock_user.sync_ratings_to_simkl = False
    mock_user.trakt_access_token = "valid_token"
    mock_user.sync_ratings_to_trakt = False

    with (
        patch("backend.services.sync.async_session_factory") as mock_factory,
        patch(
            "backend.services.sync.ensure_fresh_token", new_callable=AsyncMock
        ) as mock_refresh,
        patch(
            "backend.services.sync.sync_post_duel", new_callable=AsyncMock
        ) as mock_sync,
        patch(
            "backend.services.sync.sync_post_duel_simkl", new_callable=AsyncMock
        ) as mock_simkl_sync,
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none.return_value = mock_user
        mock_session.execute.return_value = mock_exec_result

        await sync_ratings_background(
            uuid.uuid4(), uuid.uuid4(), 1100, uuid.uuid4(), 900
        )

        mock_refresh.assert_not_awaited()
        mock_sync.assert_not_awaited()
        mock_simkl_sync.assert_not_awaited()


@pytest.mark.asyncio
async def testsync_ratings_background_syncs_when_opt_in():
    """sync_ratings_background syncs when sync_ratings_to_trakt is True."""
    from backend.services.sync import sync_ratings_background

    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    mock_user = MagicMock()
    mock_user.sync_ratings_to_simkl = False
    mock_user.trakt_access_token = "valid_token"
    mock_user.sync_ratings_to_trakt = True

    mock_movie_row_a = MagicMock()
    mock_movie_row_a.id = mid_a
    mock_movie_row_a.trakt_id = 111
    mock_movie_row_a.media_type = "movie"

    mock_movie_row_b = MagicMock()
    mock_movie_row_b.id = mid_b
    mock_movie_row_b.trakt_id = 222
    mock_movie_row_b.media_type = "movie"

    mock_user_result = MagicMock()
    mock_user_result.scalar_one_or_none.return_value = mock_user

    mock_movies_result = MagicMock()
    mock_movies_result.all.return_value = [mock_movie_row_a, mock_movie_row_b]

    mock_elos_result = MagicMock()
    mock_elos_result.all.return_value = _rating_rows(
        (900, 1, 1, 3), (1100, 2, 1, 3)
    )

    mock_session = AsyncMock()
    mock_session.execute.side_effect = [
        mock_user_result,
        mock_movies_result,
        mock_elos_result,
    ]

    with (
        patch("backend.services.sync.async_session_factory") as mock_factory,
        patch(
            "backend.services.sync.ensure_fresh_token",
            new_callable=AsyncMock,
            return_value=mock_user,
        ),
        patch(
            "backend.services.sync.sync_post_duel", new_callable=AsyncMock
        ) as mock_sync,
        patch(
            "backend.services.sync.trakt_token_needs_refresh", return_value=False
        ),
    ):
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        await sync_ratings_background(uid, mid_a, 1100, mid_b, 900)

        mock_sync.assert_awaited_once_with(
            "valid_token", [(111, 1100), (222, 900)], {900: 5, 1100: 9}, "movie"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("needs_refresh", [True, False])
async def testsync_ratings_background_locks_user_only_for_refresh(needs_refresh):
    """The user row is locked (FOR UPDATE) only to serialize a token refresh.

    An unconditional lock queued every post-duel sync behind a long pool sync,
    holding pooled connections until statement_timeout (#662-#665).
    """
    from sqlalchemy.dialects import postgresql

    from backend.services.sync import sync_ratings_background

    uid = uuid.uuid4()
    mid_a = uuid.uuid4()
    mid_b = uuid.uuid4()

    captured_stmts = []

    mock_user = MagicMock()
    mock_user.sync_ratings_to_simkl = False
    mock_user.trakt_access_token = "token"
    mock_user.sync_ratings_to_trakt = True

    mock_rows = [
        MagicMock(id=mid_a, trakt_id=111, simkl_id=None, media_type="movie"),
        MagicMock(id=mid_b, trakt_id=222, simkl_id=None, media_type="movie"),
    ]

    with (
        patch("backend.services.sync.async_session_factory") as mock_factory,
        patch(
            "backend.services.sync.ensure_fresh_token", new_callable=AsyncMock
        ) as mock_refresh,
        patch("backend.services.sync.sync_post_duel", new_callable=AsyncMock),
        patch(
            "backend.services.sync.trakt_token_needs_refresh",
            return_value=needs_refresh,
        ),
    ):
        mock_session = AsyncMock()
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_refresh.return_value = mock_user

        mock_user_result = MagicMock()
        mock_user_result.scalar_one_or_none.return_value = mock_user
        mock_user_result.scalar_one.return_value = mock_user
        mock_movies_result = MagicMock()
        mock_movies_result.all.return_value = mock_rows

        async def capture_execute(stmt, *args, **kwargs):
            captured_stmts.append(stmt)
            if "users" in str(stmt):
                return mock_user_result
            return mock_movies_result

        mock_session.execute.side_effect = capture_execute

        await sync_ratings_background(uid, mid_a, 1100, mid_b, 900)

        def compiled(stmt):
            return str(stmt.compile(dialect=postgresql.dialect())).upper()

        assert "FOR UPDATE" not in compiled(captured_stmts[0])
        locked = [st for st in captured_stmts if "FOR UPDATE" in compiled(st)]
        if needs_refresh:
            assert len(locked) == 1
            mock_refresh.assert_awaited_once_with(mock_user, mock_session)
        else:
            assert locked == []
            mock_refresh.assert_not_awaited()
        mock_session.commit.assert_awaited_once()


async def _run_sync_with_providers(
    user, rows, mid_a, mid_b, *, needs_refresh=False, refresh_error=None
):
    """Run sync_ratings_background with both provider pushes patched.

    Returns (trakt push mock, SIMKL push mock, token refresh mock, statements executed).
    """
    from backend.db_models import User
    from backend.services.sync import sync_ratings_background

    captured_stmts = []
    later_results = []
    user_result = MagicMock()
    user_result.scalar_one_or_none.return_value = user
    movies_result = MagicMock()
    movies_result.all.return_value = rows
    elos_result = MagicMock()
    elos_result.all.return_value = _rating_rows((900, 0, 1, 2), (1100, 1, 1, 2))

    async def execute(stmt, *args, **kwargs):
        captured_stmts.append(stmt)
        if stmt.column_descriptions[0]["entity"] is User:
            return user_result
        later_results.append(stmt)
        return [movies_result, elos_result][len(later_results) - 1]

    with (
        patch("backend.services.sync.async_session_factory") as mock_factory,
        patch(
            "backend.services.sync.ensure_fresh_token",
            new_callable=AsyncMock,
            side_effect=refresh_error,
        ) as mock_refresh,
        patch(
            "backend.services.sync.sync_post_duel", new_callable=AsyncMock
        ) as mock_sync,
        patch(
            "backend.services.sync.sync_post_duel_simkl", new_callable=AsyncMock
        ) as mock_simkl_sync,
        patch(
            "backend.services.sync.trakt_token_needs_refresh",
            return_value=needs_refresh,
        ),
    ):
        mock_session = AsyncMock()
        mock_session.execute.side_effect = execute
        mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)

        await sync_ratings_background(user.id, mid_a, 1100, mid_b, 900)

    return mock_sync, mock_simkl_sync, mock_refresh, captured_stmts


def _provider_user(*, trakt: bool, simkl: bool):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.sync_ratings_to_trakt = trakt
    user.trakt_access_token = "trakt-token" if trakt else None
    user.sync_ratings_to_simkl = simkl
    user.simkl_access_token = "simkl-token" if simkl else None
    return user


@pytest.mark.asyncio
async def testsync_ratings_background_syncs_to_simkl_when_opt_in():
    """With only SIMKL sync on, ratings go to SIMKL by SIMKL id and Trakt is untouched."""
    from sqlalchemy.dialects import postgresql

    mid_a, mid_b = uuid.uuid4(), uuid.uuid4()
    rows = [
        MagicMock(id=mid_b, trakt_id=222, simkl_id=444, media_type="movie"),
        MagicMock(id=mid_a, trakt_id=111, simkl_id=333, media_type="movie"),
    ]

    mock_sync, mock_simkl_sync, mock_refresh, stmts = await _run_sync_with_providers(
        _provider_user(trakt=False, simkl=True), rows, mid_a, mid_b
    )

    mock_simkl_sync.assert_awaited_once_with(
        "simkl-token", [(333, 1100), (444, 900)], {900: 3, 1100: 8}, "movie"
    )
    mock_sync.assert_not_awaited()
    mock_refresh.assert_not_awaited()
    assert not any(
        "FOR UPDATE" in str(st.compile(dialect=postgresql.dialect())).upper()
        for st in stmts
    )


@pytest.mark.asyncio
async def testsync_ratings_background_skips_titles_without_simkl_id():
    """A title with no SIMKL id is left out of the SIMKL push."""
    mid_a, mid_b = uuid.uuid4(), uuid.uuid4()
    rows = [
        MagicMock(id=mid_a, trakt_id=111, simkl_id=None, media_type="movie"),
        MagicMock(id=mid_b, trakt_id=222, simkl_id=444, media_type="movie"),
    ]

    _, mock_simkl_sync, _, _ = await _run_sync_with_providers(
        _provider_user(trakt=False, simkl=True), rows, mid_a, mid_b
    )

    mock_simkl_sync.assert_awaited_once_with(
        "simkl-token", [(444, 900)], {900: 3, 1100: 8}, "movie"
    )


@pytest.mark.asyncio
async def testsync_ratings_background_no_simkl_push_without_simkl_ids():
    """When neither title has a SIMKL id, nothing is pushed to SIMKL."""
    mid_a, mid_b = uuid.uuid4(), uuid.uuid4()
    rows = [
        MagicMock(id=mid_a, trakt_id=111, simkl_id=None, media_type="movie"),
        MagicMock(id=mid_b, trakt_id=222, simkl_id=None, media_type="movie"),
    ]

    _, mock_simkl_sync, _, _ = await _run_sync_with_providers(
        _provider_user(trakt=False, simkl=True), rows, mid_a, mid_b
    )

    mock_simkl_sync.assert_not_awaited()


@pytest.mark.asyncio
async def testsync_ratings_background_syncs_to_both_providers():
    """With both syncs on, each provider gets its own token and ids."""
    mid_a, mid_b = uuid.uuid4(), uuid.uuid4()
    rows = [
        MagicMock(id=mid_a, trakt_id=111, simkl_id=333, media_type="movie"),
        MagicMock(id=mid_b, trakt_id=222, simkl_id=444, media_type="movie"),
    ]

    mock_sync, mock_simkl_sync, _, _ = await _run_sync_with_providers(
        _provider_user(trakt=True, simkl=True), rows, mid_a, mid_b
    )

    mock_sync.assert_awaited_once_with(
        "trakt-token", [(111, 1100), (222, 900)], {900: 3, 1100: 8}, "movie"
    )
    mock_simkl_sync.assert_awaited_once_with(
        "simkl-token", [(333, 1100), (444, 900)], {900: 3, 1100: 8}, "movie"
    )


@pytest.mark.asyncio
async def testsync_ratings_background_trakt_refresh_failure_still_syncs_simkl():
    """A failed Trakt token refresh skips Trakt but still pushes to SIMKL."""
    import httpx

    mid_a, mid_b = uuid.uuid4(), uuid.uuid4()
    rows = [
        MagicMock(id=mid_a, trakt_id=111, simkl_id=333, media_type="movie"),
        MagicMock(id=mid_b, trakt_id=222, simkl_id=444, media_type="movie"),
    ]

    mock_sync, mock_simkl_sync, mock_refresh, _ = await _run_sync_with_providers(
        _provider_user(trakt=True, simkl=True),
        rows,
        mid_a,
        mid_b,
        needs_refresh=True,
        refresh_error=httpx.HTTPStatusError(
            "401", request=MagicMock(), response=MagicMock(status_code=401)
        ),
    )

    mock_refresh.assert_awaited_once()
    mock_sync.assert_not_awaited()
    mock_simkl_sync.assert_awaited_once_with(
        "simkl-token", [(333, 1100), (444, 900)], {900: 3, 1100: 8}, "movie"
    )


@pytest.mark.asyncio
async def testsync_ratings_background_simkl_only_never_refreshes_trakt_token():
    """With Trakt sync off, an expiring Trakt token is neither locked nor refreshed."""
    from sqlalchemy.dialects import postgresql

    mid_a, mid_b = uuid.uuid4(), uuid.uuid4()
    rows = [
        MagicMock(id=mid_a, trakt_id=111, simkl_id=333, media_type="movie"),
        MagicMock(id=mid_b, trakt_id=222, simkl_id=444, media_type="movie"),
    ]
    user = _provider_user(trakt=False, simkl=True)
    user.trakt_access_token = "lingering-trakt-token"

    _, mock_simkl_sync, mock_refresh, stmts = await _run_sync_with_providers(
        user, rows, mid_a, mid_b, needs_refresh=True
    )

    mock_refresh.assert_not_awaited()
    assert not any(
        "FOR UPDATE" in str(st.compile(dialect=postgresql.dialect())).upper()
        for st in stmts
    )
    mock_simkl_sync.assert_awaited_once()


@pytest.mark.asyncio
async def testsync_ratings_background_skips_simkl_without_simkl_token():
    """SIMKL sync switched on with no linked SIMKL token pushes nothing to SIMKL."""
    mid_a, mid_b = uuid.uuid4(), uuid.uuid4()
    rows = [
        MagicMock(id=mid_a, trakt_id=111, simkl_id=333, media_type="movie"),
        MagicMock(id=mid_b, trakt_id=222, simkl_id=444, media_type="movie"),
    ]
    user = _provider_user(trakt=False, simkl=True)
    user.simkl_access_token = None

    _, mock_simkl_sync, _, _ = await _run_sync_with_providers(
        user, rows, mid_a, mid_b
    )

    mock_simkl_sync.assert_not_awaited()
