"""Tests for the pluggable Fetcher layer (no real network)."""

from geo_audit.crawler import Crawler, CrawlResult
from geo_audit.fetcher import FallbackFetcher, FetchResponse, RequestsFetcher


def _resp(rendered_with: str) -> FetchResponse:
    return FetchResponse(
        final_url="https://example.com/",
        status_code=200,
        ok=True,
        text="<html></html>",
        rendered_with=rendered_with,
    )


class _OkFetcher:
    def __init__(self, rendered_with: str):
        self._rendered_with = rendered_with
        self.calls = 0

    def fetch(self, url: str) -> FetchResponse:
        self.calls += 1
        return _resp(self._rendered_with)


class _BoomFetcher:
    def __init__(self):
        self.calls = 0

    def fetch(self, url: str) -> FetchResponse:
        self.calls += 1
        raise RuntimeError("browser unavailable")


class _FakeFetcher:
    """A Fetcher stand-in that returns a canned response and records the URL."""

    def __init__(self, response: FetchResponse):
        self._response = response
        self.fetched = []

    def fetch(self, url: str) -> FetchResponse:
        self.fetched.append(url)
        return self._response


def test_crawler_uses_injected_fetcher():
    fake = _FakeFetcher(
        FetchResponse(
            final_url="https://example.com/",
            status_code=200,
            ok=True,
            headers={"content-encoding": "gzip"},
            text="<html><head><title>Hi</title></head><body>ok</body></html>",
            content_length=42,
            elapsed_ms=123.0,
            rendered_with="playwright",
        )
    )
    # Use a fake sidecar fetch so robots/llms/sitemap don't hit the network.
    crawler = Crawler(fetcher=fake)
    crawler._fetch_text = lambda url: None  # type: ignore[assignment]

    result = crawler.crawl("example.com")

    assert fake.fetched == ["https://example.com"]
    assert isinstance(result, CrawlResult)
    assert result.ok is True
    assert result.status_code == 200
    assert result.final_url == "https://example.com/"
    assert result.elapsed_ms == 123.0
    assert result.rendered_with == "playwright"
    assert "Hi" in result.html


def test_crawler_defaults_to_requests_fetcher():
    crawler = Crawler()
    assert isinstance(crawler.fetcher, RequestsFetcher)
    # The default fetcher shares the crawler's session (so headers/UA apply).
    assert crawler.fetcher.session is crawler.session


def test_fetch_failure_is_graceful():
    class _Boom:
        def fetch(self, url):
            raise RuntimeError("browser crashed")

    crawler = Crawler(fetcher=_Boom())
    result = crawler.crawl("example.com")
    assert result.ok is False
    assert result.error and "browser crashed" in result.error


def test_fallback_uses_primary_when_it_succeeds():
    primary = _OkFetcher("playwright")
    fallback = _OkFetcher("requests")
    resp = FallbackFetcher(primary, fallback).fetch("https://example.com")
    assert resp.rendered_with == "playwright"
    assert primary.calls == 1
    assert fallback.calls == 0  # fallback never touched


def test_fallback_degrades_when_primary_fails():
    primary = _BoomFetcher()
    fallback = _OkFetcher("requests")
    resp = FallbackFetcher(primary, fallback).fetch("https://example.com")
    # Audit still gets a result, marked as the fallback path.
    assert resp.rendered_with == "requests"
    assert primary.calls == 1
    assert fallback.calls == 1


def test_crawler_with_fallback_records_requests_on_degrade():
    # End-to-end through Crawler: primary (JS) fails → requests result, no crash.
    crawler = Crawler(fetcher=FallbackFetcher(_BoomFetcher(), _OkFetcher("requests")))
    crawler._fetch_text = lambda url: None  # no sidecar network
    result = crawler.crawl("example.com")
    assert result.ok is True
    assert result.rendered_with == "requests"
