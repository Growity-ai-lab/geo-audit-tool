"""Tests for bot-access and page-speed scoring (no network — fake CrawlResult)."""

import gzip

from geo_audit.crawler import (
    BOT_MAX_SCORE,
    SPEED_MAX_SCORE,
    Crawler,
    CrawlResult,
    _looks_like_html,
    _looks_like_sitemap,
    analyze_bot_access,
    analyze_page_speed,
    normalize_url,
)

SITEMAP_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<url><loc>https://x.com/a</loc></url>"
    "<url><loc>https://x.com/b</loc></url>"
    "</urlset>"
)

SITEMAP_INDEX_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    "<sitemap><loc>https://x.com/sitemap-1.xml</loc></sitemap>"
    "</sitemapindex>"
)


class _FakeResp:
    def __init__(self, status_code=200, content=b"", text="", encoding="utf-8"):
        self.status_code = status_code
        self.content = content
        self.text = text
        self.encoding = encoding
        self.headers = {}


def _crawl_result(robots_text="", base="https://x.com"):
    return CrawlResult(url=base, final_url=base, robots_text=robots_text)


def test_normalize_url_adds_scheme():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("http://x.com") == "http://x.com"


def test_looks_like_html_detects_soft_404():
    # A soft-404 page served for a missing /llms.txt must be rejected.
    assert _looks_like_html("<!DOCTYPE html><html><head>...") is True
    assert _looks_like_html("<html lang='tr'><body>404</body></html>") is True
    # A real llms.txt (markdown) must NOT be flagged as HTML.
    assert _looks_like_html("# Acme\n\n## Docs\n- https://acme.com/x") is False
    assert _looks_like_html("") is False


def test_all_bots_allowed_full_score():
    cr = CrawlResult(
        url="https://x",
        robots_found=True,
        bot_access={"GPTBot": True, "ClaudeBot": True, "PerplexityBot": True},
    )
    result = analyze_bot_access(cr)
    assert result.score == BOT_MAX_SCORE


def test_one_bot_blocked_partial_score():
    cr = CrawlResult(
        url="https://x",
        robots_found=True,
        bot_access={"GPTBot": True, "ClaudeBot": True, "PerplexityBot": False},
    )
    result = analyze_bot_access(cr)
    assert round(result.score, 2) == round(BOT_MAX_SCORE * 2 / 3, 2)
    assert any(f.severity == "fail" for f in result.findings)


def test_no_robots_means_all_allowed():
    cr = CrawlResult(url="https://x", robots_found=False, bot_access={})
    result = analyze_bot_access(cr)
    assert result.score == BOT_MAX_SCORE


def test_parse_bot_access_blocks_named_bot():
    robots = "User-agent: GPTBot\nDisallow: /\n"
    access = Crawler._parse_bot_access(robots, "https://x.com/page")
    assert access["GPTBot"] is False
    assert access["ClaudeBot"] is True


def test_page_speed_full_score():
    cr = CrawlResult(
        url="https://x",
        final_url="https://x",
        status_code=200,
        elapsed_ms=300,
        headers={"content-encoding": "br"},
        sitemap_found=True,
        sitemap_url="https://x/sitemap.xml",
    )
    result = analyze_page_speed(cr)
    assert result.score == SPEED_MAX_SCORE


def test_page_speed_slow_and_insecure():
    cr = CrawlResult(
        url="http://x",
        final_url="http://x",
        status_code=200,
        elapsed_ms=5000,
        headers={},
        sitemap_found=False,
    )
    result = analyze_page_speed(cr)
    # status only: 2.0 of 10
    assert result.score == 2.0
    assert any("HTTPS" in f.message for f in result.findings)


# --- sitemap detection ------------------------------------------------- #


def test_looks_like_sitemap_case_and_namespace_insensitive():
    assert _looks_like_sitemap(SITEMAP_XML) is True
    assert _looks_like_sitemap(SITEMAP_XML.replace("urlset", "UrlSet")) is True
    assert _looks_like_sitemap(SITEMAP_INDEX_XML) is True
    assert _looks_like_sitemap("<html><body>404</body></html>") is False


def test_check_sitemap_found_via_robots_directive(monkeypatch):
    crawler = Crawler()
    result = _crawl_result(robots_text="User-agent: *\nSitemap: https://x.com/sitemap.xml\n")

    def _fake_get(url, **kw):
        assert url == "https://x.com/sitemap.xml"
        return _FakeResp(200, content=SITEMAP_XML.encode(), text=SITEMAP_XML)

    monkeypatch.setattr(crawler.session, "get", _fake_get)
    crawler._check_sitemap(result)
    assert result.sitemap_found is True
    assert result.sitemap_url == "https://x.com/sitemap.xml"
    assert result.sitemap_url_count == 2


def test_check_sitemap_handles_gzip_without_content_encoding_header(monkeypatch):
    """A static .xml.gz served without a Content-Encoding header must still
    be recognized — requests won't auto-decompress it, so resp.text is raw
    binary garbage. This reproduces a real-world false negative (Ideasoft)."""
    crawler = Crawler()
    result = _crawl_result(
        robots_text="User-agent: *\nSitemap: https://x.com/sitemap.xml.gz\n"
    )
    gz_bytes = gzip.compress(SITEMAP_XML.encode())

    def _fake_get(url, **kw):
        return _FakeResp(
            200, content=gz_bytes, text=gz_bytes.decode("latin-1")
        )

    monkeypatch.setattr(crawler.session, "get", _fake_get)
    crawler._check_sitemap(result)
    assert result.sitemap_found is True
    assert result.sitemap_url_count == 2


def test_check_sitemap_falls_back_to_conventional_paths(monkeypatch):
    crawler = Crawler()
    result = _crawl_result(robots_text="User-agent: *\nDisallow:\n")  # no Sitemap: line

    def _fake_get(url, **kw):
        if url == "https://x.com/sitemap_index.xml":
            return _FakeResp(200, content=SITEMAP_INDEX_XML.encode(), text=SITEMAP_INDEX_XML)
        return _FakeResp(404, content=b"", text="")

    monkeypatch.setattr(crawler.session, "get", _fake_get)
    crawler._check_sitemap(result)
    assert result.sitemap_found is True
    assert result.sitemap_url == "https://x.com/sitemap_index.xml"


def test_check_sitemap_not_found_when_all_candidates_missing(monkeypatch):
    crawler = Crawler()
    result = _crawl_result(robots_text="User-agent: *\nDisallow:\n")

    monkeypatch.setattr(
        crawler.session, "get", lambda url, **kw: _FakeResp(404, content=b"", text="")
    )
    crawler._check_sitemap(result)
    assert result.sitemap_found is False
