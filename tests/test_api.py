"""API wiring tests — no real network, no real browser, SQLite DB.

Fixtures (deterministic audits + in-memory DB) live in conftest.py.
"""


def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_create_audit_returns_score_and_artifacts(client):
    resp = client.post("/audits", json={"url": "example.com", "client": "Dardanel"})
    assert resp.status_code == 202  # accepted; eager mode finishes it inline
    body = resp.json()

    assert body["status"] == "done"
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
