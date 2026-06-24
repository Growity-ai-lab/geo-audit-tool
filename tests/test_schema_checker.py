"""Tests for schema.org / JSON-LD detection."""

from geo_audit import schema_checker
from geo_audit.schema_checker import MAX_SCORE, POINTS_PER_TYPE


def test_no_structured_data_scores_zero():
    result = schema_checker.analyze("<html><body><p>hi</p></body></html>")
    assert result.score == 0.0
    assert any(f.severity == "fail" for f in result.findings)


def test_all_key_types_detected_full_score():
    html = """
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"FAQPage"},
      {"@type":"Organization"},
      {"@type":"HowTo"},
      {"@type":"Article"}
    ]}
    </script>
    """
    result = schema_checker.analyze(html)
    assert result.score == MAX_SCORE


def test_article_alias_counts_as_article():
    html = """
    <script type="application/ld+json">
    {"@type":"NewsArticle","headline":"x"}
    </script>
    """
    result = schema_checker.analyze(html)
    assert result.score == POINTS_PER_TYPE
    assert any("Article schema detected" in f.message for f in result.findings)


def test_type_as_list_is_parsed():
    html = """
    <script type="application/ld+json">
    {"@type":["WebPage","FAQPage"]}
    </script>
    """
    result = schema_checker.analyze(html)
    assert result.score == POINTS_PER_TYPE


def test_microdata_fallback_warns_about_jsonld():
    html = '<div itemscope itemtype="https://schema.org/Organization"></div>'
    result = schema_checker.analyze(html)
    assert result.score == POINTS_PER_TYPE
    assert any("microdata" in f.message.lower() for f in result.findings)


def test_malformed_jsonld_does_not_crash():
    html = '<script type="application/ld+json">{not valid json,,}</script>'
    result = schema_checker.analyze(html)
    assert result.score == 0.0
