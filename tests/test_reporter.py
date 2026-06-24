"""Tests for report rendering (HTML export)."""

from geo_audit.crawler import CrawlResult
from geo_audit.reporter import render_html
from geo_audit.scorer import score


def _report(html="<html><head><title>x</title></head><body><h1>H</h1></body></html>"):
    cr = CrawlResult(
        url="https://x", final_url="https://x", status_code=200, ok=True, html=html,
        headers={"content-encoding": "gzip"}, elapsed_ms=300,
        bot_access={"GPTBot": True, "ClaudeBot": True, "PerplexityBot": True},
        sitemap_found=True, sitemap_url="https://x/sitemap.xml",
    )
    return score(cr)


def test_html_contains_branding_and_score():
    out = render_html(_report(), brand="Growity", client="Dardanel")
    assert "<!DOCTYPE html>" in out
    assert 'lang="tr"' in out
    assert "Growity" in out
    assert "Dardanel" in out
    assert "/100" in out
    assert "Kategori Detayları" in out


def test_html_escapes_client_input():
    out = render_html(_report(), client="<script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_html_unreachable_report():
    cr = CrawlResult(url="https://x", ok=False, error="boom", html="")
    out = render_html(score(cr))
    assert "erişilemedi" in out.lower()
    assert "boom" in out
