"""Tests for rankings pure functions: _sanitize_csv_cell, elo_to_letterboxd_rating, parse_decade."""

from __future__ import annotations

import pytest

from backend.services.rankings import (
    _sanitize_csv_cell,
    elo_to_letterboxd_rating,
    parse_decade,
)


# ---------------------------------------------------------------------------
# _sanitize_csv_cell — formula injection prevention (Item 6)
# ---------------------------------------------------------------------------


class TestSanitizeCsvCell:
    def test_equals_prefix(self):
        assert _sanitize_csv_cell("=CMD('calc')") == "'=CMD('calc')"

    def test_plus_prefix(self):
        assert _sanitize_csv_cell("+CMD('calc')") == "'+CMD('calc')"

    def test_minus_prefix(self):
        assert _sanitize_csv_cell("-CMD('calc')") == "'-CMD('calc')"

    def test_at_prefix(self):
        assert _sanitize_csv_cell("@SUM(A1)") == "'@SUM(A1)"

    def test_tab_prefix(self):
        assert _sanitize_csv_cell("\tCMD") == "'\tCMD"

    def test_newline_prefix(self):
        assert _sanitize_csv_cell("\nCMD") == "'\nCMD"

    def test_safe_string_passthrough(self):
        assert _sanitize_csv_cell("Normal Title") == "Normal Title"


# ---------------------------------------------------------------------------
# elo_to_letterboxd_rating — boundary tests (Item 7)
# ---------------------------------------------------------------------------


class TestEloToLetterboxdRating:
    def test_floor_600(self):
        assert elo_to_letterboxd_rating(600) == 1

    def test_ceiling_1400(self):
        assert elo_to_letterboxd_rating(1400) == 10

    def test_below_floor(self):
        assert elo_to_letterboxd_rating(100) == 1

    def test_above_ceiling(self):
        assert elo_to_letterboxd_rating(2000) == 10


# ---------------------------------------------------------------------------
# parse_decade (Item 8)
# ---------------------------------------------------------------------------


class TestParseDecade:
    def test_1990s(self):
        assert parse_decade("1990s") == (1990, 1999)

    def test_2020s(self):
        assert parse_decade("2020s") == (2020, 2029)
