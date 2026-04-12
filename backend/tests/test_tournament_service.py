"""Tests for tournament service pure functions."""

import pytest

from backend.services.tournament import _num_rounds, generate_seeded_bracket


class TestGenerateSeededBracket:
    def test_bracket_size_8(self):
        result = generate_seeded_bracket(8)
        assert len(result) == 4
        # Standard 8-team seeding: 1v8, 4v5, 2v7, 3v6
        assert result == [(1, 8), (4, 5), (2, 7), (3, 6)]

    def test_bracket_size_16(self):
        result = generate_seeded_bracket(16)
        assert len(result) == 8
        # First match is always 1 vs 16
        assert result[0] == (1, 16)
        # All seeds 1-16 appear exactly once
        seeds = set()
        for a, b in result:
            seeds.add(a)
            seeds.add(b)
        assert seeds == set(range(1, 17))

    def test_bracket_size_32(self):
        result = generate_seeded_bracket(32)
        assert len(result) == 16
        # First match is always 1 vs 32
        assert result[0] == (1, 32)
        # All seeds 1-32 appear exactly once
        seeds = set()
        for a, b in result:
            seeds.add(a)
            seeds.add(b)
        assert seeds == set(range(1, 33))

    def test_bracket_size_2(self):
        assert generate_seeded_bracket(2) == [(1, 2)]

    def test_bracket_size_4(self):
        assert generate_seeded_bracket(4) == [(1, 4), (2, 3)]

    def test_bracket_size_64(self):
        result = generate_seeded_bracket(64)
        assert len(result) == 32
        seeds = set()
        for a, b in result:
            seeds.add(a)
            seeds.add(b)
        assert seeds == set(range(1, 65))

    def test_unsupported_size(self):
        with pytest.raises(ValueError, match="Unsupported bracket size"):
            generate_seeded_bracket(12)


class TestNumRounds:
    def test_size_2(self):
        assert _num_rounds(2) == 1

    def test_size_4(self):
        assert _num_rounds(4) == 2

    def test_size_8(self):
        assert _num_rounds(8) == 3

    def test_size_16(self):
        assert _num_rounds(16) == 4

    def test_size_32(self):
        assert _num_rounds(32) == 5

    def test_size_64(self):
        assert _num_rounds(64) == 6
