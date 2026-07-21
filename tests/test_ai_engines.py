"""Tests for LLM engine adapters — response parsing via mocked SDKs/HTTP.

These verify the parsing/extraction logic (text + cited sources), not real
network calls, which require live keys.
"""

import sys
import types

import geo_audit.ai_engines as eng
from geo_audit.ai_engines import (
    ClaudeEngine,
    GeminiEngine,
    OpenAIEngine,
    PerplexityEngine,
    _parse_names,
    build_engines,
    build_extractor,
)


def _ns(**kw):
    return types.SimpleNamespace(**kw)


# --- OpenAI --------------------------------------------------------------- #


def test_openai_engine_parses_text_and_citations(monkeypatch):
    resp = _ns(
        output_text="Tara Robotik önde geliyor.",
        output=[
            _ns(content=[
                _ns(annotations=[
                    _ns(url="https://tararobotik.com/x"),
                    _ns(url="https://abb.com"),
                ])
            ])
        ],
    )

    class _Client:
        def __init__(self, api_key=None):
            self.responses = _ns(create=lambda **kw: resp)

    monkeypatch.setitem(sys.modules, "openai", _ns(OpenAI=_Client))
    out = OpenAIEngine("key").query("prompt")
    assert out.text == "Tara Robotik önde geliyor."
    assert out.sources == ["https://tararobotik.com/x", "https://abb.com"]


# --- Perplexity ----------------------------------------------------------- #


def test_perplexity_engine_parses_content_and_citations(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": "Yanıt metni."}}],
                "citations": ["https://tararobotik.com/a", "https://kuka.com"],
            }

    monkeypatch.setattr(eng.requests, "post", lambda *a, **k: _Resp())
    out = PerplexityEngine("key").query("prompt")
    assert out.text == "Yanıt metni."
    assert out.sources == ["https://tararobotik.com/a", "https://kuka.com"]


def test_perplexity_engine_reads_search_results_shape(monkeypatch):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "choices": [{"message": {"content": "x"}}],
                "search_results": [{"url": "https://abb.com"}, {"title": "no url"}],
            }

    monkeypatch.setattr(eng.requests, "post", lambda *a, **k: _Resp())
    out = PerplexityEngine("key").query("prompt")
    assert out.sources == ["https://abb.com"]


# --- Gemini --------------------------------------------------------------- #


def test_gemini_engine_parses_grounding(monkeypatch):
    resp = _ns(
        text="Gemini yanıtı.",
        candidates=[
            _ns(grounding_metadata=_ns(grounding_chunks=[
                _ns(web=_ns(uri="https://wikipedia.org/x")),
                _ns(web=_ns(uri="https://tararobotik.com")),
            ]))
        ],
    )

    class _Client:
        def __init__(self, api_key=None):
            self.models = _ns(generate_content=lambda **kw: resp)

    fake_types = _ns(
        GenerateContentConfig=lambda **kw: None,
        Tool=lambda **kw: None,
        GoogleSearch=lambda **kw: None,
    )
    monkeypatch.setitem(sys.modules, "google", _ns(genai=_ns(Client=_Client)))
    monkeypatch.setitem(sys.modules, "google.genai", _ns(Client=_Client, types=fake_types))
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)
    out = GeminiEngine("key").query("prompt")
    assert out.text == "Gemini yanıtı."
    assert out.sources == ["https://wikipedia.org/x", "https://tararobotik.com"]


def test_gemini_engine_recovers_from_model_404(monkeypatch):
    """A 404 on the configured model → discover a live Flash model and retry."""
    resp = _ns(text="OK", candidates=[])
    calls = {"generate": []}

    listed = [
        _ns(name="models/gemini-2.0-flash", supported_actions=["generateContent"]),
        _ns(name="models/imagen-4.0", supported_actions=["predict"]),
        _ns(name="models/gemini-flash-latest", supported_actions=["generateContent"]),
        _ns(name="models/gemini-embedding-2", supported_actions=["embedContent"]),
    ]

    class _Client:
        def __init__(self, api_key=None):
            self.models = _ns(
                generate_content=self._gen,
                list=lambda: iter(listed),
            )

        def _gen(self, **kw):
            calls["generate"].append(kw["model"])
            if kw["model"] == "gemini-2.0-flash":
                raise RuntimeError("404 NOT_FOUND: model no longer available")
            return resp

    fake_types = _ns(
        GenerateContentConfig=lambda **kw: None,
        Tool=lambda **kw: None,
        GoogleSearch=lambda **kw: None,
    )
    monkeypatch.setitem(sys.modules, "google", _ns(genai=_ns(Client=_Client)))
    monkeypatch.setitem(sys.modules, "google.genai", _ns(Client=_Client, types=fake_types))
    monkeypatch.setitem(sys.modules, "google.genai.types", fake_types)

    eng = GeminiEngine("key", model="gemini-2.0-flash")
    out = eng.query("prompt")
    assert out.text == "OK"
    # Picked the flash+latest alias and cached it for the next call.
    assert calls["generate"] == ["gemini-2.0-flash", "gemini-flash-latest"]
    assert eng._resolved_model == "gemini-flash-latest"
    eng.query("again")
    assert calls["generate"][-1] == "gemini-flash-latest"  # no re-discovery


# --- Claude --------------------------------------------------------------- #


def test_claude_engine_parses_text_and_citations(monkeypatch):
    resp = _ns(content=[
        _ns(type="text", text="Claude yanıtı.", citations=[_ns(url="https://tararobotik.com")]),
        _ns(type="web_search_tool_result", content=[_ns(url="https://abb.com")]),
    ])

    class _Client:
        def __init__(self, api_key=None):
            self.messages = _ns(create=lambda **kw: resp)

    monkeypatch.setitem(sys.modules, "anthropic", _ns(Anthropic=_Client))
    out = ClaudeEngine("key").query("prompt")
    assert out.text == "Claude yanıtı."
    assert "https://tararobotik.com" in out.sources and "https://abb.com" in out.sources


# --- competitor name parsing ---------------------------------------------- #


def test_parse_names_json_array():
    assert _parse_names('["ABB", "KUKA"]', "Tara") == ["ABB", "KUKA"]


def test_parse_names_strips_brand_and_dupes():
    assert _parse_names('["Tara", "ABB", "ABB"]', "tara") == ["ABB"]


def test_parse_names_object_shape_and_fences():
    assert _parse_names('```json\n{"brands": ["ABB"]}\n```', "Tara") == ["ABB"]


def test_parse_names_invalid_returns_empty():
    assert _parse_names("not json", "Tara") == []
    assert _parse_names(None, "Tara") == []


# --- config-gated construction -------------------------------------------- #


def test_build_engines_only_includes_keyed_providers():
    engines = build_engines(openai_key="a", gemini_key="b")
    names = {e.name for e in engines}
    assert names == {"ChatGPT", "Gemini"}


def test_build_engines_claude_requires_explicit_enable():
    assert build_engines(claude_key="a") == []  # key alone isn't enough
    engines = build_engines(claude_key="a", enable_claude=True)
    assert [e.name for e in engines] == ["Claude"]


def test_build_extractor_prefers_openai_then_anthropic_then_none():
    assert isinstance(build_extractor(openai_key="a", anthropic_key="b"),
                      eng.OpenAICompetitorExtractor)
    assert isinstance(build_extractor(anthropic_key="b"),
                      eng.AnthropicCompetitorExtractor)
    assert build_extractor() is None
