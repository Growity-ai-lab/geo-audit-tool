"""API-level tests that the targeting overlay flows through a real audit."""


def test_no_page_type_no_keyword_omits_targeting(client):
    body = client.post("/audits", json={"url": "example.com"}).json()
    assert body["targeting"] is None


def test_page_type_produces_targeting_overlay(client):
    # conftest's fake page has an Organization schema + <h1>Başlık</h1>.
    body = client.post(
        "/audits",
        json={"url": "example.com", "page_type": "homepage", "target_keyword": "Başlık"},
    ).json()

    t = body["targeting"]
    assert t is not None
    assert t["page_type"] == "homepage"
    assert t["target_keyword"] == "Başlık"
    assert t["keyword_score"] is not None
    # Organization is expected for a homepage and present in the fixture.
    org = next(e for e in t["schema_expectations"] if e["label"] == "Organization")
    assert org["present"] is True
    # geo_score is unaffected by targeting (still a normal 0-100 value).
    assert 0 <= body["geo_score"] <= 100


def test_targeting_persists_and_round_trips(client):
    audit_id = client.post(
        "/audits", json={"url": "example.com", "page_type": "product"}
    ).json()["audit_id"]
    got = client.get(f"/audits/{audit_id}").json()
    assert got["targeting"] is not None
    assert got["targeting"]["page_type"] == "product"


def test_targeting_rendered_in_html_artifact(client):
    body = client.post(
        "/audits", json={"url": "example.com", "target_keyword": "Başlık"}
    ).json()
    html = client.get(body["html_url"])
    assert html.status_code == 200
    assert "Hedefleme" in html.text
