"""Tests for PageSpeed Insights parsing and CWV-based page-speed scoring."""

import geo_audit.pagespeed as psi_mod
from geo_audit.crawler import SPEED_MAX_SCORE, CrawlResult, analyze_page_speed
from geo_audit.pagespeed import PSIResult, fetch_psi, parse_psi

# A trimmed PSI v5 response with both lab and field data.
SAMPLE_PSI = {
    "lighthouseResult": {
        "categories": {"performance": {"score": 0.84}},
        "audits": {
            "largest-contentful-paint": {"numericValue": 2100.0},
            "cumulative-layout-shift": {"numericValue": 0.05},
        },
    },
    "loadingExperience": {
        "metrics": {"INTERACTION_TO_NEXT_PAINT": {"percentile": 180}}
    },
}


def _psi_crawl(lcp_ms=None, cls=None, inp_ms=None, perf=None, **kw) -> CrawlResult:
    return CrawlResult(
        url="https://x",
        final_url="https://x",
        status_code=200,
        sitemap_found=True,
        sitemap_url="https://x/sitemap.xml",
        psi_lcp_ms=lcp_ms,
        psi_cls=cls,
        psi_inp_ms=inp_ms,
        psi_perf_score=perf,
        psi_source="psi",
        **kw,
    )


# --- parsing -------------------------------------------------------------- #


def test_parse_psi_extracts_metrics():
    result = parse_psi(SAMPLE_PSI, strategy="mobile")
    assert result.lcp_ms == 2100.0
    assert result.cls == 0.05
    assert result.inp_ms == 180.0
    assert result.perf_score == 84.0


def test_parse_psi_handles_missing_fields():
    result = parse_psi({}, strategy="mobile")
    assert result.lcp_ms is None
    assert result.cls is None
    assert result.inp_ms is None
    assert result.perf_score is None


def test_fetch_psi_parses_ok(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return SAMPLE_PSI

    monkeypatch.setattr(psi_mod.requests, "get", lambda *a, **k: _Resp())
    result = fetch_psi("https://x", "key")
    assert isinstance(result, PSIResult)
    assert result.lcp_ms == 2100.0
    assert result.perf_score == 84.0


def test_fetch_psi_returns_none_on_http_error(monkeypatch):
    class _Resp:
        status_code = 500

        def json(self):
            return {}

    monkeypatch.setattr(psi_mod.requests, "get", lambda *a, **k: _Resp())
    assert fetch_psi("https://x", "key") is None


def test_fetch_psi_returns_none_on_exception(monkeypatch):
    def _boom(*a, **k):
        raise psi_mod.requests.RequestException("network down")

    monkeypatch.setattr(psi_mod.requests, "get", _boom)
    assert fetch_psi("https://x", "key") is None


def test_fetch_psi_returns_none_when_no_metrics(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return {"lighthouseResult": {"audits": {}}}

    monkeypatch.setattr(psi_mod.requests, "get", lambda *a, **k: _Resp())
    assert fetch_psi("https://x", "key") is None


# --- scoring -------------------------------------------------------------- #


def test_psi_mode_good_cwv_scores_high():
    cr = _psi_crawl(lcp_ms=2000, cls=0.03, inp_ms=150, perf=95)
    result = analyze_page_speed(cr)
    assert result.name == "Sayfa Hızı / Core Web Vitals"
    assert result.max_score == SPEED_MAX_SCORE
    # status+https+sitemap+LCP+CLS = 8 plus ~1.9 perf → near full.
    assert result.score >= 9.0
    assert result.metrics["lcp_ms"] == 2000
    assert result.metrics["source"] == "psi"


def test_psi_mode_poor_cwv_scores_low():
    cr = _psi_crawl(lcp_ms=6000, cls=0.4, inp_ms=700, perf=20)
    good = _psi_crawl(lcp_ms=2000, cls=0.03, inp_ms=150, perf=95)
    poor_score = analyze_page_speed(cr).score
    good_score = analyze_page_speed(good).score
    assert poor_score < good_score
    # LCP/CLS earn nothing; only status+https+sitemap (3) + small perf share.
    assert poor_score <= 4.0
    assert any(f.severity == "fail" for f in analyze_page_speed(cr).findings)


def test_psi_mode_never_exceeds_max():
    cr = _psi_crawl(lcp_ms=1, cls=0.0, inp_ms=1, perf=100)
    assert analyze_page_speed(cr).score <= SPEED_MAX_SCORE


def test_no_psi_uses_crawlability_scoring():
    # Without PSI source, the classic scheme (and its category name) is used.
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
    assert result.name == "Sayfa Hızı / Taranabilirlik"
    assert result.score == SPEED_MAX_SCORE
    assert result.metrics == {}
