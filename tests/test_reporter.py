"""Tests for report rendering (HTML export)."""

from geo_audit.aggregate import aggregate_reports
from geo_audit.crawler import CrawlResult
from geo_audit.reporter import render_html, render_list_html
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


def test_list_report_renders_pages_and_averages():
    a = _report()
    b = score(CrawlResult(url="https://b", ok=False, error="down", html=""))
    out = render_list_html(aggregate_reports([a, b]), brand="Growity", client="Acme")
    assert "<!DOCTYPE html>" in out
    assert out.count("</style>") == 1  # extra CSS injected exactly once
    assert "LİSTE RAPORU" in out
    assert "Sayfa Bazlı Skorlar" in out
    assert "Kategori Ortalamaları" in out
    assert "Acme" in out
    assert "erişilemedi" in out  # the unreachable page is shown, not dropped


def test_list_report_escapes_client_input():
    out = render_list_html(
        aggregate_reports([_report()]), client="<script>alert(1)</script>"
    )
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
