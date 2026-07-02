"""Tests for manual overrides on ambiguous (WAF-blocked) findings."""

from geo_audit import CategoryResult, Finding
from geo_audit.content_analyzer import W_LLMS_PRESENT
from geo_audit.crawler import AI_BOTS, BOT_MAX_SCORE, W_SITEMAP
from geo_audit.overrides import apply_overrides
from geo_audit.scorer import AuditReport


def _ambiguous_report() -> AuditReport:
    return AuditReport(
        url="https://x", final_url="https://x", reachable=True, error=None,
        total_score=32.0, max_score=100.0, grade="F",
        categories=[
            CategoryResult(
                key="bot_access", name="AI Bot Erişimi", score=25.0, max_score=25.0,
                findings=[
                    Finding(
                        "warn", "robots.txt erişimi doğrulanamadı...", "",
                        override_key="robots_blocked",
                    )
                ],
            ),
            CategoryResult(
                key="llms_txt", name="llms.txt", score=0.0, max_score=10.0,
                findings=[
                    Finding(
                        "warn", "llms.txt erişimi doğrulanamadı...", "",
                        override_key="llms_txt_exists",
                    )
                ],
            ),
            CategoryResult(
                key="page_speed", name="Sayfa Hızı / Taranabilirlik", score=7.0, max_score=10.0,
                findings=[
                    Finding(
                        "warn", "Sitemap erişimi doğrulanamadı...", "",
                        override_key="sitemap_exists",
                    )
                ],
            ),
        ],
    )


def test_apply_overrides_returns_new_object_base_unchanged():
    report = _ambiguous_report()
    adjusted = apply_overrides(report, {"sitemap_exists": True})
    assert adjusted is not report
    assert report.total_score == 32.0  # base untouched


def test_no_overrides_is_a_noop():
    report = _ambiguous_report()
    adjusted = apply_overrides(report, {})
    assert adjusted.total_score == report.total_score


def test_sitemap_exists_grants_remaining_half_credit():
    report = _ambiguous_report()
    adjusted = apply_overrides(report, {"sitemap_exists": True})
    page_speed = next(c for c in adjusted.categories if c.key == "page_speed")
    assert page_speed.score == 7.0 + W_SITEMAP / 2
    finding = next(f for f in page_speed.findings if f.override_key == "sitemap_exists")
    assert finding.severity == "ok"
    assert "doğrulandı" in finding.message


def test_llms_txt_exists_grants_presence_baseline():
    report = _ambiguous_report()
    adjusted = apply_overrides(report, {"llms_txt_exists": True})
    llms = next(c for c in adjusted.categories if c.key == "llms_txt")
    assert llms.score == W_LLMS_PRESENT
    finding = next(f for f in llms.findings if f.override_key == "llms_txt_exists")
    assert finding.severity == "ok"


def test_robots_blocked_deducts_one_bot_share():
    report = _ambiguous_report()
    adjusted = apply_overrides(report, {"robots_blocked": True})
    bot_access = next(c for c in adjusted.categories if c.key == "bot_access")
    per_bot = BOT_MAX_SCORE / len(AI_BOTS)
    assert bot_access.score == 25.0 - per_bot
    finding = next(f for f in bot_access.findings if f.override_key == "robots_blocked")
    assert finding.severity == "warn"
    assert "engelleniyor" in finding.message


def test_total_score_and_grade_recomputed():
    report = _ambiguous_report()
    adjusted = apply_overrides(
        report, {"sitemap_exists": True, "llms_txt_exists": True, "robots_blocked": True}
    )
    expected = sum(c.score for c in adjusted.categories)
    assert adjusted.total_score == expected
    from geo_audit.scorer import grade_for

    assert adjusted.grade == grade_for(expected)


def test_unknown_or_false_override_is_ignored():
    report = _ambiguous_report()
    adjusted = apply_overrides(report, {"sitemap_exists": False, "made_up_key": True})
    assert adjusted.total_score == report.total_score


def test_score_never_exceeds_category_max():
    report = _ambiguous_report()
    # Even if somehow called twice via a stale finding, score must clamp.
    page_speed = next(c for c in report.categories if c.key == "page_speed")
    page_speed.score = page_speed.max_score  # already at max
    adjusted = apply_overrides(report, {"sitemap_exists": True})
    ps = next(c for c in adjusted.categories if c.key == "page_speed")
    assert ps.score <= ps.max_score
