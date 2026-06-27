"""Tests for audit persistence: list, detail, client linkage."""


def test_audit_is_persisted_and_listed(client):
    created = client.post("/audits", json={"url": "example.com"}).json()
    audit_id = created["audit_id"]

    listing = client.get("/audits").json()
    assert listing["total"] == 1
    assert listing["limit"] == 20 and listing["offset"] == 0
    assert listing["items"][0]["audit_id"] == audit_id
    assert listing["items"][0]["grade"] == created["grade"]
    # The list summary must not carry the heavy report payload.
    assert "categories" not in listing["items"][0]


def test_audit_detail_roundtrips(client):
    created = client.post("/audits", json={"url": "example.com"}).json()
    audit_id = created["audit_id"]

    detail = client.get(f"/audits/{audit_id}").json()
    assert detail["audit_id"] == audit_id
    assert detail["geo_score"] == created["geo_score"]
    assert detail["categories"] == created["categories"]
    assert detail["html_url"] == created["html_url"]


def test_audit_detail_404_for_unknown(client):
    # A two-segment path is an artifact; a single unknown id is a missing audit.
    assert client.get("/audits/nonexistent-id").status_code == 404


def test_list_pagination_and_total(client):
    for _ in range(3):
        client.post("/audits", json={"url": "example.com"})

    page = client.get("/audits", params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 3
    assert len(page["items"]) == 2

    page2 = client.get("/audits", params={"limit": 2, "offset": 2}).json()
    assert len(page2["items"]) == 1


def test_audit_links_to_existing_client(client):
    cl = client.post("/clients", json={"name": "Dardanel"}).json()
    created = client.post(
        "/audits", json={"url": "example.com", "client_id": cl["id"]}
    ).json()

    assert created["client_id"] == cl["id"]
    # Filtering the list by client returns only that client's audits.
    listing = client.get("/audits", params={"client_id": cl["id"]}).json()
    assert listing["total"] == 1
    assert listing["items"][0]["client_id"] == cl["id"]


def test_audit_with_unknown_client_404s(client):
    resp = client.post(
        "/audits", json={"url": "example.com", "client_id": "ghost"}
    )
    assert resp.status_code == 404
