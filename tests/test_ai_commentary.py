"""Tests for AI-generated report commentary (mocked Anthropic client)."""

import anthropic

from api.ai_commentary import Commentary, generate_commentary
from geo_audit import CategoryResult, Finding
from geo_audit.scorer import AuditReport


def _report(reachable=True) -> AuditReport:
    return AuditReport(
        url="https://x",
        final_url="https://x",
        reachable=reachable,
        error=None,
        total_score=42.0,
        max_score=100.0,
        grade="F",
        categories=[
            CategoryResult(
                key="schema",
                name="Schema İşaretlemesi",
                score=0.0,
                max_score=25.0,
                findings=[Finding(severity="fail", message="Schema yok", recommendation="Ekle")],
            ),
        ],
    )


def test_generate_commentary_returns_none_without_api_key():
    assert generate_commentary(_report(), api_key="", model="claude-haiku-4-5") is None


def test_generate_commentary_returns_none_for_unreachable_report():
    assert (
        generate_commentary(_report(reachable=False), api_key="key", model="claude-haiku-4-5")
        is None
    )


def test_generate_commentary_success(monkeypatch):
    expected = Commentary(
        executive_summary="Site AI motorları için hazır değil.",
        category_notes=[{"key": "schema", "note": "Schema eksikliği kritik."}],
    )

    class _FakeMessages:
        def parse(self, **kwargs):
            assert kwargs["model"] == "claude-haiku-4-5"
            assert kwargs["output_format"] is Commentary

            class _Resp:
                parsed_output = expected

            return _Resp()

    class _FakeClient:
        def __init__(self, api_key=None):
            self.messages = _FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)

    result = generate_commentary(_report(), api_key="key", model="claude-haiku-4-5")
    assert result is expected
    assert result.executive_summary == "Site AI motorları için hazır değil."
    assert result.category_notes[0].key == "schema"


def test_generate_commentary_returns_none_on_api_error(monkeypatch):
    class _FakeClient:
        def __init__(self, api_key=None):
            pass

        class messages:
            @staticmethod
            def parse(**kwargs):
                raise anthropic.APIConnectionError(request=None)

    monkeypatch.setattr(anthropic, "Anthropic", _FakeClient)

    assert generate_commentary(_report(), api_key="key", model="claude-haiku-4-5") is None
