"""Tests for the list-level aggregation engine."""

from geo_audit import CategoryResult, Finding
from geo_audit.aggregate import AggregateReport, aggregate_reports
from geo_audit.scorer import AuditReport


def _report(url: str, score: float, reachable: bool = True, findings=None) -> AuditReport:
    cats = []
    if reachable:
        cats = [
            CategoryResult(
                key="schema", name="Schema İşaretlemesi", score=score / 4,
                max_score=25.0, findings=findings or [],
            ),
            CategoryResult(
                key="llms_txt", name="llms.txt", score=0.0, max_score=10.0,
                findings=[Finding("fail", "Site kök dizininde llms.txt bulunamadı.", "x")],
            ),
        ]
    return AuditReport(
        url=url, final_url=url, reachable=reachable,
        error=None if reachable else "boom",
        total_score=score if reachable else 0.0, max_score=100.0,
        grade="F", categories=cats,
    )


def test_avg_excludes_unreachable_pages():
    reports = [_report("a", 60), _report("b", 40), _report("down", 0, reachable=False)]
    agg = aggregate_reports(reports)
    assert agg.url_count == 3
    assert agg.reachable_count == 2
    assert agg.avg_score == 50.0  # (60 + 40) / 2, not / 3


def test_all_unreachable_scores_zero_f():
    agg = aggregate_reports([_report("x", 0, reachable=False)])
    assert agg.reachable_count == 0
    assert agg.avg_score == 0.0
    assert agg.grade == "F"


def test_empty_list():
    agg = aggregate_reports([])
    assert agg.url_count == 0
    assert agg.avg_score == 0.0
    assert agg.pages == []


def test_pages_preserve_order_and_reachability():
    agg = aggregate_reports([_report("a", 60), _report("down", 0, reachable=False)])
    assert [p["url"] for p in agg.pages] == ["a", "down"]
    assert agg.pages[0]["geo_score"] == 60.0 and agg.pages[0]["reachable"] is True
    assert agg.pages[1]["geo_score"] is None and agg.pages[1]["reachable"] is False


def test_category_averages_over_reachable():
    agg = aggregate_reports([_report("a", 80), _report("b", 40)])
    schema = next(c for c in agg.category_averages if c["key"] == "schema")
    # schema score = total/4 → (20 + 10) / 2 = 15
    assert schema["avg_score"] == 15.0
    assert schema["max_score"] == 25.0


def test_top_gaps_counts_shared_findings():
    # llms.txt "not found" is on both pages → page_count 2.
    agg = aggregate_reports([_report("a", 60), _report("b", 40)])
    llms_gap = next(g for g in agg.top_gaps if "llms.txt" in g["message"])
    assert llms_gap["page_count"] == 2
    assert llms_gap["severity"] == "fail"


def test_top_gaps_criticals_before_warnings():
    warn = Finding("warn", "Uyarı bulgusu", "")
    fail = Finding("fail", "Kritik bulgu", "")
    reports = [_report("a", 50, findings=[warn, fail])]
    agg = aggregate_reports(reports)
    severities = [g["severity"] for g in agg.top_gaps]
    # every fail must appear before every warn
    assert severities.index("fail") < severities.index("warn")


def test_round_trip():
    agg = aggregate_reports([_report("a", 60), _report("b", 40)])
    assert AggregateReport.from_dict(agg.to_dict()).to_dict() == agg.to_dict()
