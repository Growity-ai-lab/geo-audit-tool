"""Tests for clients CRUD."""


def test_create_and_get_client(client):
    resp = client.post(
        "/clients", json={"name": "Dardanel", "domain": "dardanel.com.tr"}
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["name"] == "Dardanel"
    assert created["domain"] == "dardanel.com.tr"
    assert created["id"]

    got = client.get(f"/clients/{created['id']}")
    assert got.status_code == 200
    assert got.json()["id"] == created["id"]


def test_list_clients(client):
    client.post("/clients", json={"name": "A"})
    client.post("/clients", json={"name": "B"})
    listing = client.get("/clients").json()
    assert {c["name"] for c in listing} == {"A", "B"}


def test_update_client(client):
    created = client.post("/clients", json={"name": "Old"}).json()
    updated = client.patch(
        f"/clients/{created['id']}", json={"name": "New", "domain": "x.com"}
    ).json()
    assert updated["name"] == "New"
    assert updated["domain"] == "x.com"


def test_delete_client(client):
    created = client.post("/clients", json={"name": "Temp"}).json()
    assert client.delete(f"/clients/{created['id']}").status_code == 204
    assert client.get(f"/clients/{created['id']}").status_code == 404


def test_missing_client_404s(client):
    assert client.get("/clients/ghost").status_code == 404
    assert client.patch("/clients/ghost", json={"name": "x"}).status_code == 404
    assert client.delete("/clients/ghost").status_code == 404


def test_create_client_requires_name(client):
    assert client.post("/clients", json={}).status_code == 422
    assert client.post("/clients", json={"name": ""}).status_code == 422


def test_deleting_client_keeps_audit_but_nulls_link(client):
    cl = client.post("/clients", json={"name": "Temp"}).json()
    audit = client.post(
        "/audits", json={"url": "example.com", "client_id": cl["id"]}
    ).json()

    client.delete(f"/clients/{cl['id']}")

    # Audit still retrievable; its client link is cleared (ON DELETE SET NULL).
    detail = client.get(f"/audits/{audit['audit_id']}")
    assert detail.status_code == 200
    listing = client.get("/audits").json()
    assert listing["total"] == 1
    assert listing["items"][0]["client_id"] is None
