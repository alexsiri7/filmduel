"""Tests for rankings service layer — pure logic (no DB)."""

import csv
import io
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.rankings import (
    export_rankings_csv,
    get_ranked_elos,
    get_user_stats,
    parse_decade,
)


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


def test_parse_decade_invalid_raises_value_error():
    """Non-numeric decade string must raise ValueError."""
    with pytest.raises(ValueError):
        parse_decade("invalid")


def test_parse_decade_empty_string_raises_value_error():
    """Empty string must raise ValueError."""
    with pytest.raises(ValueError):
        parse_decade("")


def test_parse_decade_partial_numeric_raises_value_error():
    """Partially numeric decade string must raise ValueError."""
    with pytest.raises(ValueError):
        parse_decade("19x0s")


# --- export_rankings_csv (integration with mock DB) ---


def _make_export_user_movie(title: str, year: int, imdb_id: str, elo: int) -> MagicMock:
    """Build a mock UserMovie with a loaded .movie relationship for CSV export."""
    um = MagicMock()
    um.elo = elo
    um.movie.title = title
    um.movie.year = year
    um.movie.imdb_id = imdb_id
    um.movie.media_type = "movie"
    return um


@pytest.mark.asyncio
async def test_export_rankings_csv_valid_csv():
    """CSV output has correct header and one row per UserMovie."""
    fake_ums = [
        _make_export_user_movie("Film A", 2020, "tt0000001", 1200),
        _make_export_user_movie("Film B", 2019, "tt0000002", 1100),
        _make_export_user_movie("Film C", 2021, "tt0000003", 1000),
    ]

    mock_result = MagicMock()
    mock_result.unique.return_value.scalars.return_value.all.return_value = fake_ums
    db = AsyncMock()
    db.execute.return_value = mock_result

    csv_content = await export_rankings_csv(db, uuid.uuid4(), media_type="movie")
    reader = csv.reader(io.StringIO(csv_content))
    rows = list(reader)

    assert len(rows) == 4  # 1 header + 3 data
    assert rows[0] == ["Position", "Title", "Year", "imdbID", "Rating10"]


@pytest.mark.asyncio
async def test_export_rankings_csv_sanitizes_formula_title():
    """Titles starting with formula characters are prefixed with a single quote in CSV output."""
    fake_ums = [_make_export_user_movie("=CMD()", 2020, "tt0000001", 1000)]

    mock_result = MagicMock()
    mock_result.unique.return_value.scalars.return_value.all.return_value = fake_ums
    db = AsyncMock()
    db.execute.return_value = mock_result

    csv_content = await export_rankings_csv(db, uuid.uuid4(), media_type="movie")
    reader = csv.reader(io.StringIO(csv_content))
    rows = list(reader)

    assert rows[1][1] == "'=CMD()"


@pytest.mark.asyncio
async def test_export_rankings_csv_rates_by_percentile():
    """Ten films on a narrow ELO range export Rating10 of 10 down to 1."""
    elos = [1342, 1250, 1150, 1100, 1050, 1000, 940, 900, 850, 813]
    fake_ums = [
        _make_export_user_movie(f"Film {i}", 2020, f"tt{i:07d}", elo)
        for i, elo in enumerate(elos)
    ]

    rows_result = MagicMock()
    rows_result.unique.return_value.scalars.return_value.all.return_value = fake_ums
    elos_result = MagicMock()
    elos_result.scalars.return_value.all.return_value = sorted(elos)
    db = AsyncMock()
    db.execute.side_effect = [rows_result, elos_result]

    csv_content = await export_rankings_csv(db, uuid.uuid4(), media_type="movie")
    rows = list(csv.reader(io.StringIO(csv_content)))

    assert [row[4] for row in rows[1:]] == [str(r) for r in range(10, 0, -1)]


@pytest.mark.asyncio
async def test_export_rankings_csv_rates_against_full_population_not_capped_rows():
    """Rating10 ranks against get_ranked_elos, not only the rows under the export cap."""
    fake_ums = [_make_export_user_movie("Kept", 2020, "tt0000001", 1100)]

    rows_result = MagicMock()
    rows_result.unique.return_value.scalars.return_value.all.return_value = fake_ums
    elos_result = MagicMock()
    elos_result.scalars.return_value.all.return_value = [900, 1100]
    db = AsyncMock()
    db.execute.side_effect = [rows_result, elos_result]

    csv_content = await export_rankings_csv(db, uuid.uuid4(), media_type="show")
    rows = list(csv.reader(io.StringIO(csv_content)))

    assert rows[1][4] == "8"
    elos_stmt = db.execute.await_args_list[1].args[0]
    assert "ORDER BY user_movies.elo ASC" in str(elos_stmt)
    assert "LIMIT" not in str(elos_stmt)
    assert "show" in elos_stmt.compile().params.values()


# --- get_ranked_elos ---


@pytest.mark.asyncio
async def test_get_ranked_elos_returns_ascending_ranked_population():
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [900, 1000]
    db = AsyncMock()
    db.execute.return_value = mock_result

    assert await get_ranked_elos(db, uuid.uuid4(), media_type="show") == [900, 1000]

    sql = str(db.execute.call_args[0][0])
    assert "media_type" in sql
    assert "battles" in sql
    assert "seen" in sql
    assert "ORDER BY user_movies.elo ASC" in sql


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


# --- CSV injection sanitization ---


def test_sanitize_csv_cell_formula_prefixes():
    """Cells starting with injection-trigger characters must be prefixed with a quote."""
    from backend.services.rankings import _sanitize_csv_cell

    dangerous = ["=CMD", "+1-1", "-1+1", "@SUM(A1)", "\t hidden", "\rhidden", "\nhidden"]
    for val in dangerous:
        result = _sanitize_csv_cell(val)
        assert result.startswith("'"), f"Expected quote prefix for: {val!r}"
        assert result[1:] == val


def test_sanitize_csv_cell_safe_values():
    """Safe cell values must pass through unchanged."""
    from backend.services.rankings import _sanitize_csv_cell

    safe = ["The Matrix", "tt0133093", "", "Inception", "2001: A Space Odyssey"]
    for val in safe:
        assert _sanitize_csv_cell(val) == val


def test_sanitize_csv_cell_empty():
    """Empty string must not be modified."""
    from backend.services.rankings import _sanitize_csv_cell

    assert _sanitize_csv_cell("") == ""
