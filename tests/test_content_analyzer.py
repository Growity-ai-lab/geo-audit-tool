"""Tests for content structure, meta signals, and llms.txt scoring."""

from geo_audit import content_analyzer
from geo_audit.content_analyzer import (
    LLMS_MAX_SCORE,
    MAX_SCORE,
    META_MAX_SCORE,
    W_ANSWER_FIRST,
    W_HAS_H2,
    W_SINGLE_H1,
)

GOOD_LEAD = (
    "The simplest way to brew great coffee is to use a one-to-sixteen ratio "
    "with a medium grind and water at about ninety-five degrees Celsius."
)


def _page(h1="<h1>Title</h1>", h2="", lead=GOOD_LEAD):
    return f"<html><body>{h1}<p>{lead}</p>{h2}</body></html>"


def test_perfect_content_structure():
    html = _page(h2="<h2>A</h2><p>x</p><h2>B</h2><p>y</p>")
    result = content_analyzer.analyze(html)
    assert result.score == MAX_SCORE


def test_missing_h1_fails():
    html = _page(h1="", h2="<h2>A</h2><h2>B</h2>")
    result = content_analyzer.analyze(html)
    assert result.score == MAX_SCORE - W_SINGLE_H1
    assert any(f.severity == "fail" and "H1" in f.message for f in result.findings)


def test_multiple_h1_partial_credit():
    html = _page(h1="<h1>One</h1><h1>Two</h1>", h2="<h2>A</h2><h2>B</h2>")
    result = content_analyzer.analyze(html)
    assert result.score == (W_SINGLE_H1 / 2) + W_HAS_H2 + W_ANSWER_FIRST


def test_short_lead_partial_credit():
    # 6 words: detected as a paragraph but below ANSWER_MIN_WORDS -> half credit.
    html = _page(lead="This is a short partial answer.")
    result = content_analyzer.analyze(html)
    # single H1 full, no H2, half answer-first
    assert result.score == W_SINGLE_H1 + (W_ANSWER_FIRST / 2)


def test_tiny_lead_treated_as_no_answer():
    # Below the 5-word meaningful-paragraph threshold -> no answer-first credit.
    html = _page(lead="Too short.")
    result = content_analyzer.analyze(html)
    assert result.score == W_SINGLE_H1
    assert any(f.severity == "fail" for f in result.findings)


def test_meta_full_score():
    html = """
    <html><head>
    <title>A Reasonably Descriptive Page Title Here</title>
    <meta name="description" content="This is a meta description of a sensible length used to summarize the page content for engines and previews.">
    <meta property="og:title" content="t">
    <meta property="og:description" content="d">
    <meta property="og:image" content="i">
    </head><body></body></html>
    """
    result = content_analyzer.analyze_meta(html)
    assert result.score == META_MAX_SCORE


def test_meta_missing_everything():
    result = content_analyzer.analyze_meta("<html><head></head><body></body></html>")
    assert result.score == 0.0
    assert sum(1 for f in result.findings if f.severity == "fail") >= 2


RICH_LLMS_TXT = """# Acme

> Acme sells widgets.

## Docs

- [Getting started](https://acme.com/docs/start): quickstart guide
- [API reference](https://acme.com/docs/api): full API docs
- [Pricing](https://acme.com/pricing): plans and pricing
"""


def test_llms_txt_missing():
    missing = content_analyzer.analyze_llms_txt(False)
    assert missing.score == 0.0
    assert any(f.severity == "fail" for f in missing.findings)


def test_llms_txt_rich_content_scores_full():
    result = content_analyzer.analyze_llms_txt(True, "https://x/llms.txt", RICH_LLMS_TXT)
    assert result.score == LLMS_MAX_SCORE


def test_llms_txt_empty_template_scores_low():
    # Present and non-empty (e.g. a generator-dropped stub), but no title,
    # no sections, and — critically — no real content links.
    result = content_analyzer.analyze_llms_txt(True, "https://x/llms.txt", "\n")
    # Only the "file exists" baseline is earned; well under full marks.
    assert result.score < LLMS_MAX_SCORE / 2
    assert any(f.severity == "fail" for f in result.findings)


def test_llms_txt_title_only_no_links():
    result = content_analyzer.analyze_llms_txt(True, "https://x/llms.txt", "# Acme\n")
    assert 0 < result.score < LLMS_MAX_SCORE
    assert any(f.severity == "fail" and "link" in f.message.lower() for f in result.findings)


def test_llms_txt_partial_links_scale_score():
    one_link = "# Acme\n\n## Docs\n\n- [Start](https://acme.com/start): guide\n"
    result = content_analyzer.analyze_llms_txt(True, "https://x/llms.txt", one_link)
    full = content_analyzer.analyze_llms_txt(True, "https://x/llms.txt", RICH_LLMS_TXT)
    assert 0 < result.score < full.score == LLMS_MAX_SCORE
