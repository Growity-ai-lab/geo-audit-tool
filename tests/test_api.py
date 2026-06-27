"""API wiring tests — no real network, no real browser."""

import pytest
from fastapi.testclient import TestClient

from api import service
from api.config import settings
from api.main import app
from geo_audit.crawler import Crawler
from geo_audit.fetcher import FetchResponse

PAGE_HTML = (
    "<!DOCTYPE html><html lang='tr'><head>"
    "<title>Örnek Sayfa</title>"
    "<meta name='description' content='Test açıklaması'>"
    "</head><body><h1>Başlık</h1><p>İçerik metni.</p></body></html>"
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Artifacts land in a temp dir for the test.
    monkeypatch.setattr(settings, "artifacts_dir", str(tmp_path))

    class _FakeFetcher:
        def fetch(self, url: str) -> FetchResponse:
            return FetchResponse(
                final_url="https://example.com/",
                status_code=200,
                ok=True,
                headers={"content-encoding": "gzip"},
                text=PAGE_HTML,
                content_length=len(PAGE_HTML),
                elapsed_ms=250.0,
                rendered_with="requests",
            )

    def _fake_build_crawler(render_js: bool) -> Crawler:
        crawler = Crawler(fetcher=_FakeFetcher())
        crawler._fetch_text = lambda url: None  # no sidecar network
        return crawler

    monkeypatch.setattr(service, "_build_crawler", _fake_build_crawler)
    # Stub PDF rendering so the test doesn't need Chromium.
    monkeypatch.setattr(service.pdf_mod, "html_to_pdf", lambda html: b"%PDF-1.4 fake")

    return TestClient(app)


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_audit_returns_score_and_artifacts(client):
    resp = client.post("/audits", json={"url": "example.com", "client": "Dardanel"})
    assert resp.status_code == 200
    body = resp.json()

    assert body["reachable"] is True
    assert 0 <= body["geo_score"] <= 100
    assert body["grade"] in {"A", "B", "C", "D", "E", "F"}
    assert body["rendered_with"] == "requests"
    assert body["html_url"] == f"/audits/{body['audit_id']}/report.html"
    assert body["pdf_url"] == f"/audits/{body['audit_id']}/report.pdf"
    assert any(c["key"] == "bot_access" for c in body["categories"])


def test_artifacts_are_served(client):
    body = client.post("/audits", json={"url": "example.com"}).json()

    html = client.get(body["html_url"])
    assert html.status_code == 200
    assert "text/html" in html.headers["content-type"]

    pdf = client.get(body["pdf_url"])
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")


def test_unknown_artifact_404s(client):
    resp = client.get("/audits/does-not-exist/report.pdf")
    assert resp.status_code == 404


def test_artifact_name_allowlist(client):
    # Traversal / arbitrary names are rejected by the allow-list.
    resp = client.get("/audits/whatever/secrets.txt")
    assert resp.status_code == 404
