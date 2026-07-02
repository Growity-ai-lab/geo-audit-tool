"""API tests for URL-list (batch) audits."""


def test_batch_audit_runs_all_urls_and_aggregates(client):
    resp = client.post(
        "/audits/batch",
        json={"urls": ["a.com", "b.com", "c.com"], "client": "Acme"},
    )
    assert resp.status_code == 202
    body = resp.json()

    assert body["status"] == "done"  # eager mode finishes inline
    assert body["url_count"] == 3
    assert body["reachable_count"] == 3  # fake fetcher always reachable
    assert 0 <= body["avg_score"] <= 100
    assert body["grade"] in {"A", "B", "C", "D", "E", "F"}
    assert len(body["pages"]) == 3
    assert {p["url"] for p in body["pages"]} == {"a.com", "b.com", "c.com"}
    assert all(p["status"] == "done" for p in body["pages"])
    # Each page links to its own artifacts.
    for p in body["pages"]:
        assert p["html_url"] == f"/audits/{p['audit_id']}/report.html"
    # Combined strategy report on the parent.
    assert body["html_url"] == f"/audits/{body['audit_id']}/report.html"
    assert body["category_averages"]


def test_batch_get_endpoint_round_trips(client):
    audit_id = client.post("/audits/batch", json={"urls": ["a.com"]}).json()["audit_id"]
    got = client.get(f"/audits/batch/{audit_id}")
    assert got.status_code == 200
    assert got.json()["audit_id"] == audit_id
    assert got.json()["url_count"] == 1


def test_batch_combined_report_served(client):
    body = client.post("/audits/batch", json={"urls": ["a.com", "b.com"]}).json()
    html = client.get(body["html_url"])
    assert html.status_code == 200
    assert "LİSTE RAPORU" in html.text
    assert "Sayfa Bazlı Skorlar" in html.text


def test_batch_child_pages_serve_own_report(client):
    body = client.post("/audits/batch", json={"urls": ["a.com"]}).json()
    page = body["pages"][0]
    html = client.get(page["html_url"])
    assert html.status_code == 200
    assert "text/html" in html.headers["content-type"]


def test_batch_children_hidden_from_history_list(client):
    client.post("/audits/batch", json={"urls": ["a.com", "b.com", "c.com"]})
    listing = client.get("/audits").json()
    # Only the parent list audit shows, not its 3 page children.
    list_scopes = [i["scope"] for i in listing["items"]]
    assert "list" in list_scopes
    assert "page" not in list_scopes
    assert listing["total"] == 1


def test_batch_empty_urls_rejected(client):
    resp = client.post("/audits/batch", json={"urls": []})
    assert resp.status_code == 422


def test_batch_get_missing_404s(client):
    assert client.get("/audits/batch/nope").status_code == 404


def test_single_audit_still_hidden_correctly(client):
    # A standalone single audit (no parent) still appears in history.
    client.post("/audits", json={"url": "solo.com"})
    listing = client.get("/audits").json()
    assert listing["total"] == 1
    assert listing["items"][0]["scope"] == "page"
