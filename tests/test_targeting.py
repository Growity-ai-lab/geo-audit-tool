"""Tests for the page-type/keyword targeting overlay."""

from geo_audit.targeting import (
    PAGE_TYPES,
    TargetingReport,
    analyze_targeting,
)

PRODUCT_HTML = """<html lang="tr"><head>
<title>Ton Balığı Konservesi - Dardanel</title>
<meta name="description" content="Kaliteli ton balığı konservesi çeşitleri.">
<script type="application/ld+json">{"@type":"Product","name":"Ton"}</script>
</head><body>
<h1>Ton Balığı Konservesi</h1>
<p>Ton balığı konservesi hakkında yeterince uzun bir açıklama paragrafı burada yer alır.</p>
</body></html>"""


def test_no_keyword_gives_no_coverage_score():
    r = analyze_targeting(PRODUCT_HTML, "generic", "")
    assert r.keyword_score is None
    assert r.keyword_checks == []


def test_keyword_present_scores_high():
    r = analyze_targeting(PRODUCT_HTML, "product", "ton balığı konservesi")
    assert r.keyword_score is not None and r.keyword_score >= 70
    title_check = next(c for c in r.keyword_checks if c["key"] == "title")
    assert title_check["present"] is True


def test_keyword_absent_scores_zero_and_flags():
    r = analyze_targeting(PRODUCT_HTML, "generic", "alakasız kelime öbeği")
    assert r.keyword_score == 0.0
    assert any(f["severity"] == "fail" for f in r.findings)


def test_keyword_match_is_case_insensitive():
    r = analyze_targeting(PRODUCT_HTML, "generic", "TON BALIĞI Konservesi")
    assert r.keyword_score is not None and r.keyword_score > 0


def test_page_type_expected_schemas():
    r = analyze_targeting(PRODUCT_HTML, "product", "")
    labels = {e["label"]: e["present"] for e in r.schema_expectations}
    assert labels["Product"] is True          # present in the HTML
    assert labels["Offer"] is False           # missing → advisory finding
    assert any("Offer" in f["message"] for f in r.findings)


def test_blog_expects_article_and_faq():
    r = analyze_targeting("<html><body><h1>x</h1></body></html>", "blog", "")
    labels = {e["label"] for e in r.schema_expectations}
    assert labels == {"Article", "FAQPage"}


def test_generic_expects_no_schema():
    r = analyze_targeting(PRODUCT_HTML, "generic", "")
    assert r.schema_expectations == []


def test_faq_detected_from_schema():
    html = '<html><body><script type="application/ld+json">{"@type":"FAQPage"}</script></body></html>'
    assert analyze_targeting(html, "blog", "").faq_present is True


def test_faq_detected_from_question_headings():
    html = "<html><body><h2>Nasıl saklanır?</h2><h2>Fiyat nedir?</h2></body></html>"
    assert analyze_targeting(html, "generic", "").faq_present is True


def test_faq_absent_is_flagged_for_valued_page_types():
    html = "<html><body><h1>Ürün</h1></body></html>"
    r = analyze_targeting(html, "product", "")
    assert r.faq_present is False
    assert any("FAQ" in f["message"] for f in r.findings)


def test_unknown_page_type_falls_back_to_generic():
    r = analyze_targeting(PRODUCT_HTML, "made_up", "")
    assert r.page_type == "generic"
    assert r.page_type_label == PAGE_TYPES["generic"]


def test_round_trip():
    r = analyze_targeting(PRODUCT_HTML, "product", "ton balığı")
    assert TargetingReport.from_dict(r.to_dict()).to_dict() == r.to_dict()
