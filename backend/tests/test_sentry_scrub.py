"""Tests for the Sentry before_send scrubbing hook."""

from __future__ import annotations

import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-for-unit-tests!!")

from backend.main import _scrub_sensitive  # noqa: E402


def _make_event_with_frame_vars(vars_: dict) -> dict:
    return {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [{"vars": vars_}]
                    }
                }
            ]
        }
    }



class TestScrubSensitive:
    def test_trakt_access_token_is_filtered(self):
        event = _make_event_with_frame_vars({"trakt_access_token": "abc123secret"})
        result = _scrub_sensitive(event, {})
        assert result["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"][
            "trakt_access_token"
        ] == "[Filtered]"

    def test_trakt_refresh_token_is_filtered(self):
        event = _make_event_with_frame_vars({"trakt_refresh_token": "refresh123"})
        result = _scrub_sensitive(event, {})
        frame_vars = result["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert frame_vars["trakt_refresh_token"] == "[Filtered]"

    def test_authorization_header_is_filtered(self):
        event = _make_event_with_frame_vars({"Authorization": "Bearer tok123"})
        result = _scrub_sensitive(event, {})
        frame_vars = result["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert frame_vars["Authorization"] == "[Filtered]"

    def test_dynamic_token_key_is_filtered(self):
        event = _make_event_with_frame_vars({"my_custom_token": "val"})
        result = _scrub_sensitive(event, {})
        frame_vars = result["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert frame_vars["my_custom_token"] == "[Filtered]"

    def test_secret_key_word_triggers_filter(self):
        event = _make_event_with_frame_vars({"db_secret": "hunter2"})
        result = _scrub_sensitive(event, {})
        frame_vars = result["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert frame_vars["db_secret"] == "[Filtered]"

    def test_non_sensitive_keys_are_preserved(self):
        event = _make_event_with_frame_vars({"user_id": "uuid-1234", "media_type": "movie"})
        result = _scrub_sensitive(event, {})
        frame_vars = result["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
        assert frame_vars["user_id"] == "uuid-1234"
        assert frame_vars["media_type"] == "movie"

    def test_event_without_exception_passes_through(self):
        event = {"message": "hello", "level": "info"}
        result = _scrub_sensitive(event, {})
        assert result == {"message": "hello", "level": "info"}

    def test_multiple_frames_all_scrubbed(self):
        event = {
            "exception": {
                "values": [
                    {
                        "stacktrace": {
                            "frames": [
                                {"vars": {"trakt_access_token": "tok1", "x": 1}},
                                {"vars": {"trakt_refresh_token": "ref1", "y": 2}},
                            ]
                        }
                    }
                ]
            }
        }
        result = _scrub_sensitive(event, {})
        frames = result["exception"]["values"][0]["stacktrace"]["frames"]
        assert frames[0]["vars"]["trakt_access_token"] == "[Filtered]"
        assert frames[0]["vars"]["x"] == 1
        assert frames[1]["vars"]["trakt_refresh_token"] == "[Filtered]"
        assert frames[1]["vars"]["y"] == 2
