"""API tests for the AI Visibility endpoint (fake engines, eager task)."""

import pytest

from api import tasks
from geo_audit.ai_visibility import EngineQueryResult


class _FakeEngine:
    def __init__(self, name="ChatGPT", model="gpt-4o", text="Tara Robotik iyi.", sources=None):
        self.name = name
        self.model = model
        self._text = text
        self._sources = sources or ["tararobotik.com/x"]

    def query(self, prompt):
        return EngineQueryResult(text=self._text, sources=list(self._sources))


@pytest.fixture
def fake_engines(monkeypatch):
    """Make the visibility task use fake engines (no real LLM calls / keys)."""
    monkeypatch.setattr(tasks, "build_engines", lambda **kw: [_FakeEngine()])
    monkeypatch.setattr(tasks, "build_extractor", lambda **kw: None)


def test_visibility_run_completes_and_scores(client, fake_engines):
    resp = client.post(
        "/audits/ai-visibility",
        json={"brand": "Tara Robotik", "domain": "tararobotik.com", "topic": "robotik"},
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "done"  # eager
    rep = body["report"]
    assert rep["brand"] == "Tara Robotik"
    assert rep["prompt_count"] >= 1
    assert 0 <= rep["score"] <= 100
    assert rep["engines_used"] == ["ChatGPT"]
    assert rep["api_calls"] > 0
    assert body["html_url"] == f"/audits/{body['audit_id']}/report.html"


def test_visibility_manual_prompts_included(client, fake_engines):
    body = client.post(
        "/audits/ai-visibility",
        json={
            "brand": "Tara Robotik",
            "domain": "tararobotik.com",
            "manual_prompts": ["Özel bir soru?"],
        },
    ).json()
    sources = {pr["source"] for pr in body["report"]["prompts"]}
    assert "manual" in sources


def test_visibility_report_served_as_html(client, fake_engines):
    body = client.post(
        "/audits/ai-visibility",
        json={"brand": "Tara Robotik", "domain": "tararobotik.com"},
    ).json()
    html = client.get(body["html_url"])
    assert html.status_code == 200
    assert "AI GÖRÜNÜRLÜK" in html.text


def test_visibility_get_round_trips(client, fake_engines):
    audit_id = client.post(
        "/audits/ai-visibility",
        json={"brand": "Tara Robotik", "domain": "tararobotik.com"},
    ).json()["audit_id"]
    got = client.get(f"/audits/ai-visibility/{audit_id}")
    assert got.status_code == 200
    assert got.json()["report"]["domain"] == "tararobotik.com"


def test_visibility_no_engines_configured_errors(client, monkeypatch):
    # Default config in tests has no engine keys → the task errors cleanly.
    monkeypatch.setattr(tasks, "build_engines", lambda **kw: [])
    body = client.post(
        "/audits/ai-visibility",
        json={"brand": "Tara Robotik", "domain": "tararobotik.com"},
    ).json()
    assert body["status"] == "error"
    assert "motor" in (body["error"] or "").lower()


def test_visibility_requires_brand_and_domain(client):
    assert client.post("/audits/ai-visibility", json={"brand": "", "domain": "x"}).status_code == 422
    assert client.post("/audits/ai-visibility", json={"brand": "x", "domain": ""}).status_code == 422


def test_visibility_get_missing_404s(client):
    assert client.get("/audits/ai-visibility/nope").status_code == 404


def test_visibility_shows_in_history_with_scope(client, fake_engines):
    client.post("/audits/ai-visibility", json={"brand": "Tara", "domain": "tara.com"})
    listing = client.get("/audits").json()
    assert any(i["scope"] == "ai_visibility" for i in listing["items"])
