"""Tests for the AI Visibility engine core (injected fake engines)."""

from geo_audit.ai_visibility import (
    EngineQueryResult,
    VisibilityReport,
    analyze_visibility,
    build_prompts,
    is_cited,
    is_mentioned,
    root_domain,
    score_visibility,
)


class FakeEngine:
    def __init__(self, name, model, text, sources=None, raises=False):
        self.name = name
        self.model = model
        self._text = text
        self._sources = sources or []
        self._raises = raises
        self.calls = 0

    def query(self, prompt):
        self.calls += 1
        if self._raises:
            raise RuntimeError("engine down")
        return EngineQueryResult(text=self._text, sources=list(self._sources))


class FakeExtractor:
    def __init__(self, names):
        self.names = names
        self.calls = 0

    def extract(self, text, brand):
        self.calls += 1
        return list(self.names)


# --- detection ------------------------------------------------------------ #


def test_is_mentioned_turkish_case_insensitive():
    assert is_mentioned("TARA ROBOTİK lider firma", "tara robotik") is True
    assert is_mentioned("ABB ve KUKA", "tara robotik") is False


def test_is_mentioned_alias():
    assert is_mentioned("TARA çözümleri", "Tara Robotik", ("TARA",)) is True


def test_root_domain():
    assert root_domain("https://www.tararobotik.com/x?y=1") == "tararobotik.com"
    assert root_domain("tararobotik.com") == "tararobotik.com"
    assert root_domain("sub.example.co/path") == "example.co"
    assert root_domain("") == ""


def test_root_domain_multilabel_cctld():
    # Turkish (and other) ccTLDs must keep three labels, not collapse to com.tr.
    assert root_domain("https://www.dardanel.com.tr/urunler") == "dardanel.com.tr"
    assert root_domain("dardanel.com.tr") == "dardanel.com.tr"
    assert root_domain("news.bbc.co.uk/x") == "bbc.co.uk"


def test_is_cited_matches_cctld_domain():
    assert is_cited(["dardanel.com.tr"], "https://www.dardanel.com.tr") is True
    assert is_cited(["superfresh.com.tr"], "dardanel.com.tr") is False


def test_is_cited_matches_root_domain():
    assert is_cited(["https://www.tararobotik.com/a", "abb.com"], "tararobotik.com") is True
    assert is_cited(["abb.com"], "tararobotik.com") is False
    assert is_cited([], "tararobotik.com") is False


# --- prompt building ------------------------------------------------------ #


def test_build_prompts_manual_first_then_auto_capped():
    ps = build_prompts("Tara", topic="robotik", manual_prompts=["Soru bir?", "Soru iki?"], max_prompts=4)
    assert len(ps) == 4
    assert [s for _, s in ps][:2] == ["manual", "manual"]
    assert all(s == "auto" for _, s in ps[2:])


def test_build_prompts_dedupes():
    ps = build_prompts("Tara", manual_prompts=["Aynı soru", "Aynı soru"], max_prompts=10)
    manual = [p for p, s in ps if s == "manual"]
    assert manual == ["Aynı soru"]


def test_build_prompts_topic_defaults_to_brand():
    ps = build_prompts("Tara Robotik", max_prompts=6)
    assert any("Tara Robotik" in p for p, _ in ps)


# --- scoring & orchestration ---------------------------------------------- #


def _engines():
    return [
        FakeEngine("ChatGPT", "gpt-4o", "Tara Robotik ve ABB önde.", ["tararobotik.com/x"]),
        FakeEngine("Gemini", "gemini-2.5", "ABB ve KUKA önerilir.", ["wikipedia.org"]),
    ]


def test_analyze_counts_mentions_citations_and_api_calls():
    ps = build_prompts("Tara Robotik", topic="robotik", max_prompts=2)
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=_engines(), sample_count=2, max_api_calls=100, generated_at="x",
    )
    d = rep.to_dict()
    # ChatGPT mentions+cites in all prompts; Gemini in none → 50% each.
    assert d["slot_total"] == 4  # 2 prompts × 2 engines
    assert d["mention_total"] == 2 and d["citation_total"] == 2
    assert d["score"] == 50.0
    # 2 prompts × 2 engines × 2 samples engine calls = 8 (no extractor).
    assert d["api_calls"] == 8


def test_analyze_budget_cap_stops_calls():
    ps = build_prompts("Tara Robotik", max_prompts=5)
    engines = _engines()
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=engines, sample_count=2, max_api_calls=3, generated_at="x",
    )
    # Hard cap honored: no more than 3 external calls total.
    assert rep.api_calls <= 3


def test_analyze_engine_failure_is_isolated():
    engines = [
        FakeEngine("ChatGPT", "gpt-4o", "Tara Robotik iyi.", ["tararobotik.com"]),
        FakeEngine("Gemini", "gemini-2.5", "", raises=True),
    ]
    ps = build_prompts("Tara Robotik", max_prompts=1)
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=engines, sample_count=1, max_api_calls=100, generated_at="x",
    )
    # The failing engine is surfaced (not silently dropped) but excluded from
    # scoring: only ChatGPT counts toward the denominator.
    by_engine = {e["engine"]: e for pr in rep.prompts for e in pr["engines"]}
    assert set(by_engine) == {"ChatGPT", "Gemini"}
    assert by_engine["Gemini"]["status"] == "error"
    assert by_engine["Gemini"]["samples"] == 0
    assert by_engine["Gemini"]["error"]
    # Denominator counts only the answering engine.
    assert rep.slot_total == 1
    assert rep.score == 100.0  # ChatGPT mentioned + cited on the one slot


def test_errored_engine_surfaced_in_engine_stats():
    engines = [FakeEngine("Gemini", "gemini-flash-latest", "", raises=True)]
    ps = build_prompts("Tara Robotik", max_prompts=2)
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=engines, sample_count=2, max_api_calls=100, generated_at="x",
    )
    # All engines failed → score 0 but with an explicit error, not a silent 0.
    assert rep.score == 0.0
    assert rep.slot_total == 0
    stat = next(s for s in rep.engine_stats if s["engine"] == "Gemini")
    assert stat["errored"] == 2 and stat["answered"] == 0
    assert stat["error"]


def test_budget_skip_does_not_fabricate_error():
    # An engine never reached due to the budget cap must NOT show as errored.
    engines = [
        FakeEngine("ChatGPT", "gpt-4o", "Tara Robotik iyi.", ["tararobotik.com"]),
        FakeEngine("Gemini", "gemini-2.5", "ABB.", []),
    ]
    ps = build_prompts("Tara Robotik", max_prompts=1)
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=engines, sample_count=1, max_api_calls=1, generated_at="x",
    )
    by_engine = {e["engine"]: e for pr in rep.prompts for e in pr["engines"]}
    # Gemini was never called (budget spent on ChatGPT) → omitted, not errored.
    assert "Gemini" not in by_engine


def test_analyze_extractor_called_once_per_prompt_engine():
    extractor = FakeExtractor(["ABB", "KUKA"])
    ps = build_prompts("Tara Robotik", max_prompts=1)
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=_engines(), extractor=extractor, sample_count=3,
        max_api_calls=100, generated_at="x",
    )
    # 1 prompt × 2 engines → extractor called twice (once per engine, sample 0).
    assert extractor.calls == 2
    names = {c["name"] for c in rep.competitor_ranking}
    assert "ABB" in names and "KUKA" in names


def test_extractor_never_lists_the_brand_itself():
    extractor = FakeExtractor(["Tara Robotik", "ABB"])  # brand leaks in
    ps = build_prompts("Tara Robotik", max_prompts=1)
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=_engines(), extractor=extractor, sample_count=1,
        max_api_calls=100, generated_at="x",
    )
    names = {c["name"] for c in rep.competitor_ranking}
    assert "Tara Robotik" not in names
    assert "ABB" in names


def test_source_ranking_flags_ours():
    ps = build_prompts("Tara Robotik", max_prompts=1)
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=_engines(), sample_count=1, max_api_calls=100, generated_at="x",
    )
    ours = [s for s in rep.source_ranking if s["is_ours"]]
    assert ours and ours[0]["domain"] == "tararobotik.com"


def test_empty_prompts_scores_zero():
    assert score_visibility([]) == 0.0


def test_round_trip():
    ps = build_prompts("Tara Robotik", max_prompts=2)
    rep = analyze_visibility(
        brand="Tara Robotik", domain="tararobotik.com", prompts=ps,
        engines=_engines(), sample_count=1, max_api_calls=100, generated_at="x",
    )
    assert VisibilityReport.from_dict(rep.to_dict()).to_dict() == rep.to_dict()
