"""Tests for rankings pure functions: _sanitize_csv_cell, parse_decade."""

from __future__ import annotations

from backend.services.rankings import (
    _sanitize_csv_cell,
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

    def test_carriage_return_prefix(self):
        assert _sanitize_csv_cell("\rCMD") == "'\rCMD"

    def test_safe_string_passthrough(self):
        assert _sanitize_csv_cell("Normal Title") == "Normal Title"

    def test_formula_after_semicolon(self):
        assert _sanitize_csv_cell('Heat;=HYPERLINK("x")') == 'Heat;\'=HYPERLINK("x")'

    def test_every_semicolon_field_start(self):
        assert _sanitize_csv_cell("=A;+B;C;@D") == "'=A;'+B;C;'@D"

    def test_safe_semicolon_passthrough(self):
        assert _sanitize_csv_cell("Heat; The Movie") == "Heat; The Movie"

    def test_formula_after_semicolon_and_quotes(self):
        assert _sanitize_csv_cell('X;""=CMD()') == 'X;""\'=CMD()'

    def test_formula_after_line_breaks(self):
        assert _sanitize_csv_cell("X\n=A\r+B\r\n@C") == "X\n'=A\r'+B\r\n'@C"

    def test_crlf_followed_by_safe_text_passthrough(self):
        assert _sanitize_csv_cell("X\r\nY") == "X\r\nY"


# ---------------------------------------------------------------------------
# parse_decade (Item 8)
# ---------------------------------------------------------------------------


class TestParseDecade:
    def test_1990s(self):
        assert parse_decade("1990s") == (1990, 1999)

    def test_2020s(self):
        assert parse_decade("2020s") == (2020, 2029)
