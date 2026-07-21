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


def test_targeting_block_rendered_when_present():
    from geo_audit.targeting import analyze_targeting

    report = _report()
    report.targeting = analyze_targeting(
        '<html><head><title>Ton</title></head><body><h1>Ton</h1></body></html>',
        "product",
        "ton",
    ).to_dict()
    out = render_html(report)
    assert "Hedefleme" in out
    assert "Hedef kelime" in out
    assert "Product" in out  # expected-schema chip for a product page


def test_targeting_absent_renders_nothing():
    out = render_html(_report())  # no targeting set
    assert "card targeting" not in out  # the card section isn't emitted
    assert "Hedef kelime" not in out


def test_visibility_report_renders_sections():
    from geo_audit.ai_visibility import EngineQueryResult, analyze_visibility, build_prompts
    from geo_audit.reporter import render_visibility_html

    class _FE:
        def __init__(self, name):
            self.name = name
            self.model = "m"

        def query(self, prompt):
            return EngineQueryResult(text="Tara Robotik iyi bir firma.", sources=["tararobotik.com/x"])

    ps = build_prompts("Tara Robotik", max_prompts=1)
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=[_FE("ChatGPT")], sample_count=2, max_api_calls=50, generated_at="14.07.2026",
    )
    out = render_visibility_html(rep, brand="Growity")
    assert "<!DOCTYPE html>" in out
    assert out.count("</style>") == 1  # extra CSS injected exactly once
    assert "AI GÖRÜNÜRLÜK" in out
    assert "Motor Dağılımı" in out
    assert "Prompt Bazlı Sonuçlar" in out
    assert "SİZ" in out  # our domain flagged in source ranking
    assert "2/2" in out  # sample-ratio pill


def test_visibility_report_surfaces_engine_errors():
    from geo_audit.ai_visibility import analyze_visibility, build_prompts
    from geo_audit.reporter import render_visibility_html

    class _Broken:
        name = "Gemini"
        model = "gemini-flash-latest"

        def query(self, prompt):
            raise RuntimeError("404 NOT_FOUND model not available")

    ps = build_prompts("Tara Robotik", max_prompts=1)
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=[_Broken()], sample_count=1, max_api_calls=50, generated_at="14.07.2026",
    )
    out = render_visibility_html(rep, brand="Growity")
    # The failure is shown loudly, not as a silent 0.
    assert "Bazı motorlar yanıt veremedi" in out
    assert "Model bulunamadı (404)" in out
