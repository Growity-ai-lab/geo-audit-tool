"""Tests for SPA detection and the raw-vs-rendered render-gap feature."""

from api import service
from api.config import settings
from geo_audit import CategoryResult
from geo_audit.crawler import Crawler
from geo_audit.fetcher import FetchResponse
from geo_audit.scorer import AuditReport, build_render_comparison, looks_like_spa

# An empty client-rendered shell vs a fully server-rendered page.
SHELL_HTML = (
    "<!DOCTYPE html><html lang='tr'><head></head>"
    "<body><div id='root'></div><script src='/app.js'></script></body></html>"
)
FULL_HTML = (
    "<!DOCTYPE html><html lang='tr'><head><title>Günsan Elektrik</title>"
    "<meta name='description' content='Günsan elektrik anahtar ve priz çözümleri.'>"
    "<script type='application/ld+json'>"
    '{"@context":"https://schema.org","@type":"Organization","name":"Günsan"}'
    "</script></head><body><h1>Günsan Elektrik</h1><h2>Ürünler</h2>"
    "<p>Günsan, anahtar ve priz serilerinde yeterince uzun bir tanıtım metni.</p>"
    "</body></html>"
)


def _cat(k, n, s, m):
    return CategoryResult(key=k, name=n, score=s, max_score=m)


def _report(score, grade, schema, content, meta):
    return AuditReport(
        "https://x", "https://x", True, None, score, 100, grade,
        [
            _cat("bot_access", "AI Bot", 25, 25),
            _cat("llms_txt", "llms", 10, 10),
            _cat("schema", "Schema", schema, 25),
            _cat("content", "İçerik", content, 20),
            _cat("meta", "Meta", meta, 10),
            _cat("page_speed", "Hız", 7, 10),
        ],
    )


# --- engine helpers ------------------------------------------------------- #


def test_looks_like_spa_true_for_empty_shell():
    assert looks_like_spa(_report(42, "F", 0, 0, 0)) is True


def test_looks_like_spa_false_for_rich_page():
    assert looks_like_spa(_report(80, "B", 20, 18, 9)) is False


def test_looks_like_spa_false_when_unreachable():
    rep = _report(0, "F", 0, 0, 0)
    rep.reachable = False
    assert looks_like_spa(rep) is False


def test_build_render_comparison_delta_and_flag():
    raw = _report(42, "F", 0, 0, 0)
    rendered = _report(59, "E", 6.3, 6, 7)
    comp = build_render_comparison(raw, rendered)
    assert comp["delta_total"] == 17.0
    assert comp["spa_suspected"] is True
    schema = next(d for d in comp["deltas"] if d["key"] == "schema")
    assert schema["raw"] == 0 and schema["rendered"] == 6.3 and schema["delta"] == 6.3


# --- API integration ------------------------------------------------------ #


def _fetcher(html: str, rendered_with: str):
    class _F:
        def fetch(self, url: str) -> FetchResponse:
            return FetchResponse(
                final_url="https://example.com/",
                status_code=200,
                ok=True,
                headers={"content-encoding": "gzip"},
                text=html,
                content_length=len(html),
                elapsed_ms=120.0,
                rendered_with=rendered_with,
            )

    return _F()


def _install_shell_vs_full(monkeypatch):
    """_build_crawler → shell for raw (no JS), full for JS-rendered."""

    def _fake(render_js: bool, with_psi: bool = True) -> Crawler:
        if render_js:
            crawler = Crawler(fetcher=_fetcher(FULL_HTML, "playwright"))
        else:
            crawler = Crawler(fetcher=_fetcher(SHELL_HTML, "requests"))
        crawler._fetch_text = lambda url: None
        return crawler

    monkeypatch.setattr(service, "_build_crawler", _fake)


def test_spa_auto_detected_on_plain_audit(client, monkeypatch):
    _install_shell_vs_full(monkeypatch)
    body = client.post("/audits", json={"url": "example.com"}).json()
    assert body["status"] == "done"
    assert body["rendered_with"] == "requests"
    assert body["spa_suspected"] is True
    assert body["render_comparison"] is None


def test_rich_page_not_flagged(client, monkeypatch):
    _install_shell_vs_full(monkeypatch)
    monkeypatch.setattr(settings, "enable_js_render", True)
    body = client.post(
        "/audits", json={"url": "example.com", "render_js": True}
    ).json()
    assert body["rendered_with"] == "playwright"
    assert body["spa_suspected"] is False


def test_compare_mode_reports_gap(client, monkeypatch):
    _install_shell_vs_full(monkeypatch)
    monkeypatch.setattr(settings, "enable_js_render", True)

    body = client.post(
        "/audits", json={"url": "example.com", "compare_render": True}
    ).json()

    assert body["rendered_with"] == "playwright"  # primary = rendered
    comp = body["render_comparison"]
    assert comp is not None
    assert comp["delta_total"] > 0
    assert comp["spa_suspected"] is True
    assert comp["rendered"]["geo_score"] > comp["raw"]["geo_score"]
    assert body["spa_suspected"] is True

    # The comparison round-trips through the detail endpoint (stored in report_json).
    detail = client.get(f"/audits/{body['audit_id']}").json()
    assert detail["render_comparison"]["delta_total"] == comp["delta_total"]
