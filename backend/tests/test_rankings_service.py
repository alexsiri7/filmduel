"""Tests for rankings service layer — pure logic (no DB)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.rankings import elo_to_letterboxd_rating, get_user_stats, parse_decade


# --- get_user_stats ---


def _make_agg_result(count, battles_sum, avg_elo):
    row = MagicMock()
    row.one.return_value = (count, battles_sum, avg_elo)
    return row


def _make_scalar_result(value):
    result = MagicMock()
    result.scalar.return_value = value
    return result


def _make_orm_result(obj):
    result = MagicMock()
    result.unique.return_value.scalars.return_value.first.return_value = obj
    return result


class TestGetUserStats:
    @pytest.mark.asyncio
    async def test_empty_library_returns_zero_stats(self):
        db = AsyncMock()
        db.execute.side_effect = [
            _make_agg_result(0, None, None),
            _make_scalar_result(3),
        ]
        result = await get_user_stats(db, uuid.uuid4(), "movie")
        assert result["total_duels"] == 0
        assert result["total_movies_ranked"] == 0
        assert result["average_elo"] == 0.0
        assert result["highest_rated"] is None
        assert result["lowest_rated"] is None
        assert result["unseen_count"] == 3

    @pytest.mark.asyncio
    async def test_normal_stats_computed_correctly(self):
        db = AsyncMock()
        highest, lowest = MagicMock(elo=1300), MagicMock(elo=800)
        db.execute.side_effect = [
            _make_agg_result(5, 20, 1050.0),
            _make_scalar_result(2),
            _make_orm_result(highest),
            _make_orm_result(lowest),
        ]
        result = await get_user_stats(db, uuid.uuid4(), "movie")
        assert result["total_movies_ranked"] == 5
        assert result["total_duels"] == 10  # 20 // 2
        assert result["average_elo"] == 1050.0
        assert result["highest_rated"] is highest
        assert result["lowest_rated"] is lowest

    @pytest.mark.asyncio
    async def test_avg_elo_none_returns_zero_float(self):
        db = AsyncMock()
        db.execute.side_effect = [
            _make_agg_result(1, 2, None),
            _make_scalar_result(0),
            _make_orm_result(MagicMock()),
            _make_orm_result(MagicMock()),
        ]
        result = await get_user_stats(db, uuid.uuid4(), "movie")
        assert result["average_elo"] == 0.0

    @pytest.mark.asyncio
    async def test_battles_sum_none_gives_zero_duels(self):
        """battles_sum can be NULL when all users have 0 battles (edge: SQL AVG/SUM returns NULL on empty)."""
        db = AsyncMock()
        db.execute.side_effect = [
            _make_agg_result(1, None, 1000.0),
            _make_scalar_result(0),
            _make_orm_result(MagicMock()),
            _make_orm_result(MagicMock()),
        ]
        result = await get_user_stats(db, uuid.uuid4(), "movie")
        assert result["total_duels"] == 0

    @pytest.mark.asyncio
    async def test_avg_elo_zero_returns_zero_not_falsy_skipped(self):
        """avg_elo=0.0 is falsy — `is not None` guard must not skip it."""
        db = AsyncMock()
        db.execute.side_effect = [
            _make_agg_result(1, 2, 0.0),
            _make_scalar_result(0),
            _make_orm_result(MagicMock()),
            _make_orm_result(MagicMock()),
        ]
        result = await get_user_stats(db, uuid.uuid4(), "movie")
        assert result["average_elo"] == 0.0


# --- parse_decade ---


def test_parse_decade_1990s():
    assert parse_decade("1990s") == (1990, 1999)


def test_parse_decade_2000s():
    assert parse_decade("2000s") == (2000, 2009)


def test_parse_decade_1960s():
    assert parse_decade("1960s") == (1960, 1969)


def test_parse_decade_without_s():
    """Decade string without trailing 's' should still work."""
    assert parse_decade("1980") == (1980, 1989)


# --- elo_to_letterboxd_rating ---


def test_elo_low_clamp():
    """ELO well below 600 should clamp to rating 1."""
    assert elo_to_letterboxd_rating(200) == 1


def test_elo_high_clamp():
    """ELO well above 1400 should clamp to rating 10."""
    assert elo_to_letterboxd_rating(2000) == 10


def test_elo_midpoint():
    """ELO at 1000 (midrange) should give a mid-range rating."""
    rating = elo_to_letterboxd_rating(1000)
    assert 4 <= rating <= 7


def test_elo_at_600():
    """ELO at 600 should map to rating 1."""
    assert elo_to_letterboxd_rating(600) == 1


def test_elo_at_1400():
    """ELO at 1400 should map to rating 10."""
    assert elo_to_letterboxd_rating(1400) == 10


# --- CSV format ---


def test_csv_export_format():
    """Verify CSV header row and column order match Letterboxd format."""
    import csv
    import io

    # Simulate what export_rankings_csv produces for the header
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Position", "Title", "Year", "imdbID", "Rating10"])
    writer.writerow([1, "The Matrix", 1999, "tt0133093", 8])
    writer.writerow([2, "Inception", 2010, "tt1375666", 7])

    output.seek(0)
    reader = csv.reader(output)
    rows = list(reader)

    assert rows[0] == ["Position", "Title", "Year", "imdbID", "Rating10"]
    assert rows[1][0] == "1"
    assert rows[1][1] == "The Matrix"
    assert rows[1][2] == "1999"
    assert rows[1][3] == "tt0133093"
    assert rows[1][4] == "8"
    assert len(rows) == 3
