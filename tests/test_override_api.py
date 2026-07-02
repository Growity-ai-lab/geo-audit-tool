"""API tests for manual overrides on ambiguous findings (PATCH /audits/{id}/overrides)."""

import copy

from api import models, repository
from api.schemas import AuditRequest


def _inject_ambiguous_sitemap_finding(db_session, audit_id: str) -> None:
    """Directly mutate a completed audit's stored report to carry an
    ambiguous sitemap finding, as a real WAF-blocked crawl would produce.

    Deep-copy is required: report_json's nested categories/findings lists
    would otherwise still be shared with the loaded object, so SQLAlchemy's
    dirty-check sees no net change and silently skips the UPDATE.
    """
    session = db_session()
    audit = session.get(models.Audit, audit_id)
    data = copy.deepcopy(audit.report_json)
    for cat in data["categories"]:
        if cat["key"] == "page_speed":
            cat["findings"].append(
                {
                    "severity": "warn",
                    "message": "Sitemap erişimi doğrulanamadı...",
                    "recommendation": "",
                    "override_key": "sitemap_exists",
                }
            )
    audit.report_json = data
    session.commit()
    session.close()


def test_override_confirms_ambiguous_finding_and_raises_score(client, db_session):
    resp = client.post("/audits", json={"url": "example.com"})
    audit_id = resp.json()["audit_id"]
    before_score = resp.json()["geo_score"]

    _inject_ambiguous_sitemap_finding(db_session, audit_id)

    patch = client.patch(
        f"/audits/{audit_id}/overrides", json={"overrides": {"sitemap_exists": True}}
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["overrides"] == {"sitemap_exists": True}
    assert body["geo_score"] > before_score

    page_speed = next(c for c in body["categories"] if c["key"] == "page_speed")
    finding = next(f for f in page_speed["findings"] if f["override_key"] == "sitemap_exists")
    assert finding["severity"] == "ok"

    # Persisted: a plain GET reflects the same overridden state.
    got = client.get(f"/audits/{audit_id}").json()
    assert got["overrides"] == {"sitemap_exists": True}
    assert got["geo_score"] == body["geo_score"]


def test_override_can_be_retracted(client, db_session):
    resp = client.post("/audits", json={"url": "example.com"})
    audit_id = resp.json()["audit_id"]
    baseline_score = resp.json()["geo_score"]

    _inject_ambiguous_sitemap_finding(db_session, audit_id)
    client.patch(f"/audits/{audit_id}/overrides", json={"overrides": {"sitemap_exists": True}})

    # Retract: setting it back to False must restore the original score.
    patch = client.patch(
        f"/audits/{audit_id}/overrides", json={"overrides": {"sitemap_exists": False}}
    )
    assert patch.status_code == 200
    assert patch.json()["geo_score"] == baseline_score


def test_override_unknown_key_rejected(client):
    resp = client.post("/audits", json={"url": "example.com"})
    audit_id = resp.json()["audit_id"]

    patch = client.patch(
        f"/audits/{audit_id}/overrides", json={"overrides": {"made_up_key": True}}
    )
    assert patch.status_code == 422


def test_override_missing_audit_404s(client):
    patch = client.patch(
        "/audits/does-not-exist/overrides", json={"overrides": {"sitemap_exists": True}}
    )
    assert patch.status_code == 404


def test_override_on_report_less_audit_409s(client, db_session):
    session = db_session()
    audit = repository.create_queued_audit(
        session,
        audit_id="queued-only",
        req=AuditRequest(url="https://example.com"),
        user_id=None,
    )
    session.close()

    patch = client.patch(
        f"/audits/{audit.id}/overrides", json={"overrides": {"sitemap_exists": True}}
    )
    assert patch.status_code == 409


def test_artifact_html_reflects_override(client, db_session):
    resp = client.post("/audits", json={"url": "example.com"})
    audit_id = resp.json()["audit_id"]

    _inject_ambiguous_sitemap_finding(db_session, audit_id)
    client.patch(f"/audits/{audit_id}/overrides", json={"overrides": {"sitemap_exists": True}})

    html = client.get(f"/audits/{audit_id}/report.html")
    assert html.status_code == 200
    assert "manuel olarak doğrulandı" in html.text
