"""Tests for the aggregation / grading engine."""

from geo_audit.crawler import CrawlResult
from geo_audit.scorer import AuditReport, grade_for, score


def test_grade_boundaries():
    assert grade_for(95) == "A"
    assert grade_for(85) == "B"
    assert grade_for(75) == "C"
    assert grade_for(65) == "D"
    assert grade_for(55) == "E"
    assert grade_for(10) == "F"


def test_unreachable_returns_failing_report():
    cr = CrawlResult(url="https://x", ok=False, error="boom", html="")
    report = score(cr)
    assert report.reachable is False
    assert report.total_score == 0.0
    assert report.grade == "F"


def test_max_score_is_100():
    cr = CrawlResult(url="https://x", ok=True, html="<html></html>")
    report = score(cr)
    assert report.max_score == 100.0
    assert {c.key for c in report.categories} == {
        "bot_access",
        "llms_txt",
        "schema",
        "content",
        "meta",
        "page_speed",
    }


def test_full_marks_page_scores_100():
    html = """
    <html><head>
    <title>How to Brew Great Coffee at Home Easily</title>
    <meta name="description" content="A complete beginner guide to brewing great coffee at home, covering grind size, water ratio, and the best methods for results.">
    <meta property="og:title" content="t">
    <meta property="og:description" content="d">
    <meta property="og:image" content="i">
    <script type="application/ld+json">
    {"@graph":[{"@type":"FAQPage"},{"@type":"Organization"},{"@type":"HowTo"},{"@type":"Article"}]}
    </script>
    </head><body>
    <h1>How to Brew Great Coffee</h1>
    <p>The simplest way to brew great coffee is to use a one-to-sixteen coffee-to-water ratio with a medium grind and water at about ninety-five degrees Celsius for a balanced cup.</p>
    <h2>Grind</h2><p>x</p><h2>Ratio</h2><p>y</p>
    </body></html>
    """
    cr = CrawlResult(
        url="https://x",
        final_url="https://x",
        status_code=200,
        ok=True,
        html=html,
        headers={"content-encoding": "gzip"},
        elapsed_ms=200,
        robots_found=False,
        bot_access={"GPTBot": True, "ClaudeBot": True, "PerplexityBot": True},
        llms_txt_found=True,
        llms_txt_url="https://x/llms.txt",
        sitemap_found=True,
        sitemap_url="https://x/sitemap.xml",
    )
    report = score(cr)
    assert report.total_score == 100.0
    assert report.grade == "A"


def test_to_dict_round_trips_keys():
    cr = CrawlResult(url="https://x", ok=True, html="<html></html>")
    d = score(cr).to_dict()
    assert "geo_score" in d and "categories" in d
    assert isinstance(d["categories"], list)
