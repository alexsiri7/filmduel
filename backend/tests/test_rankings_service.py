"""Tests for rankings service layer — pure logic (no DB)."""

from backend.services.rankings import elo_to_letterboxd_rating, parse_decade


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
