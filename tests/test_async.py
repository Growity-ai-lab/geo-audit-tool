"""Tests for the async (queued → done/error) audit lifecycle.

The suite runs Celery eagerly, so by default a POST finishes inline. These
tests additionally simulate the not-yet-processed (queued) state and the
worker-error path.
"""

from api import service, tasks


def test_eager_audit_completes(client):
    body = client.post("/audits", json={"url": "example.com"}).json()
    assert body["status"] == "done"
    assert body["geo_score"] is not None
    # Detail endpoint agrees.
    detail = client.get(f"/audits/{body['audit_id']}").json()
    assert detail["status"] == "done"
    assert detail["geo_score"] == body["geo_score"]


def test_queued_state_before_processing(client, monkeypatch):
    # Simulate a real broker: enqueue without running the task.
    monkeypatch.setattr(tasks.run_audit_task, "delay", lambda **kwargs: None)

    resp = client.post("/audits", json={"url": "example.com"})
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "queued"
    assert body["geo_score"] is None
    assert body["pdf_url"] is None

    # Polling the detail endpoint still shows queued (no result yet).
    detail = client.get(f"/audits/{body['audit_id']}").json()
    assert detail["status"] == "queued"

    # It still appears in the list with its queued status.
    listing = client.get("/audits").json()
    assert listing["total"] == 1
    assert listing["items"][0]["status"] == "queued"


def test_worker_error_is_recorded(client, monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("crawl exploded")

    monkeypatch.setattr(service, "run_audit", _boom)

    body = client.post("/audits", json={"url": "example.com"}).json()
    assert body["status"] == "error"
    assert body["geo_score"] is None
    assert "crawl exploded" in (body["error"] or "")

    detail = client.get(f"/audits/{body['audit_id']}").json()
    assert detail["status"] == "error"
