"""Tests for the __Host- cookie-name rule."""

from backend.utils.cookies import cookie_name


def test_cookie_name_prefixed_when_secure():
    assert cookie_name("filmduel_session", True) == "__Host-filmduel_session"


def test_cookie_name_bare_when_not_secure():
    assert cookie_name("filmduel_session", False) == "filmduel_session"
