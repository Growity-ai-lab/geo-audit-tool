"""Tests for bot-access and page-speed scoring (no network — fake CrawlResult)."""

from geo_audit.crawler import (
    BOT_MAX_SCORE,
    SPEED_MAX_SCORE,
    Crawler,
    CrawlResult,
    analyze_bot_access,
    analyze_page_speed,
    normalize_url,
)


def test_normalize_url_adds_scheme():
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("http://x.com") == "http://x.com"


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
