"""Tests for env-var parsing helpers in api/config.py."""

from api.config import _split_csv


def test_split_csv_strips_whitespace_and_drops_blanks():
    assert _split_csv(" https://a.com , https://b.com ,, ") == [
        "https://a.com",
        "https://b.com",
    ]


def test_split_csv_strips_trailing_slash():
    # A hand-typed dashboard value (e.g. copied from a browser address bar)
    # often carries a trailing slash; a browser's Origin header never does,
    # so CORSMiddleware's exact-match check would otherwise silently reject it.
    assert _split_csv("https://geo-audit-frontend.onrender.com/") == [
        "https://geo-audit-frontend.onrender.com"
    ]


def test_split_csv_handles_multiple_trailing_slashes():
    assert _split_csv("https://x.com//") == ["https://x.com"]
