"""Weighted scoring engine.

Runs every analyzer against a CrawlResult, aggregates the per-category
CategoryResults into a single 0-100 GEO Score, and assigns a letter grade.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from . import CategoryResult
from . import content_analyzer, crawler as crawler_mod, schema_checker

# Category order for reporting (also documents the weight of each).
CATEGORY_ORDER = [
    "bot_access",   # 25
    "llms_txt",     # 10
    "schema",       # 25
    "content",      # 20
    "meta",         # 10
    "page_speed",   # 10
]


@dataclass
class AuditReport:
    """The complete result of a GEO audit."""

    url: str
    final_url: str
    reachable: bool
    error: Optional[str]
    total_score: float
    max_score: float
    grade: str
    categories: List[CategoryResult] = field(default_factory=list)
    # Set by the orchestration layer, not score(): a heuristic that the page is
    # a client-side-rendered SPA (on-page signals collapse without JS), and an
    # optional raw-vs-rendered comparison ("what AI sees vs what users see").
    spa_suspected: bool = False
    render_comparison: Optional[dict] = None
    # Set by the orchestration layer: AI-generated narrative commentary
    # (executive summary + per-category rationale), or None if not generated
    # (no API key configured, or generation failed).
    ai_commentary: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "reachable": self.reachable,
            "error": self.error,
            "geo_score": round(self.total_score, 1),
            "max_score": self.max_score,
            "grade": self.grade,
            "spa_suspected": self.spa_suspected,
            "render_comparison": self.render_comparison,
            "ai_commentary": self.ai_commentary,
            "categories": [c.to_dict() for c in self.categories],
        }


def grade_for(score: float) -> str:
    """Map a 0-100 score to a letter grade."""
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    if score >= 50:
        return "E"
    return "F"


def grade_description(score: float) -> str:
    """Short Turkish interpretation of the overall score (for reports)."""
    if score >= 90:
        return "Mükemmel — site AI motorları için güçlü şekilde optimize edilmiş."
    if score >= 80:
        return "İyi — sağlam bir temel var, birkaç iyileştirme ile öne çıkar."
    if score >= 70:
        return "Orta-iyi — temel sinyaller mevcut, önemli fırsatlar var."
    if score >= 60:
        return "Orta — kritik eksikler GEO görünürlüğünü sınırlıyor."
    if score >= 50:
        return "Zayıf — AI motorlarında alıntılanma şansı düşük."
    return "Kritik — site AI arama motorları için büyük ölçüde hazır değil."


def score(crawl_result: "crawler_mod.CrawlResult") -> AuditReport:
    """Run all analyzers and build the aggregated AuditReport."""
    if not crawl_result.ok and not crawl_result.html:
        # Page unreachable — return an empty, failing report.
        return AuditReport(
            url=crawl_result.url,
            final_url=crawl_result.final_url or crawl_result.url,
            reachable=False,
            error=crawl_result.error,
            total_score=0.0,
            max_score=100.0,
            grade="F",
            categories=[],
        )

    html = crawl_result.html

    results = {
        "bot_access": crawler_mod.analyze_bot_access(crawl_result),
        "llms_txt": content_analyzer.analyze_llms_txt(
            crawl_result.llms_txt_found,
            crawl_result.llms_txt_url,
            crawl_result.llms_txt_content,
        ),
        "schema": schema_checker.analyze(html),
        "content": content_analyzer.analyze(html),
        "meta": content_analyzer.analyze_meta(html),
        "page_speed": crawler_mod.analyze_page_speed(crawl_result),
    }

    categories = [results[key] for key in CATEGORY_ORDER]
    total = sum(c.score for c in categories)
    max_total = sum(c.max_score for c in categories)

    return AuditReport(
        url=crawl_result.url,
        final_url=crawl_result.final_url or crawl_result.url,
        reachable=True,
        error=crawl_result.error if not crawl_result.ok else None,
        total_score=total,
        max_score=max_total,
        grade=grade_for(total),
        categories=categories,
    )


# On-page categories whose signals only exist once HTML/JS has produced content.
# If these collapse on a raw (no-JS) fetch, the page is likely a client-rendered
# SPA — the same near-empty shell most AI crawlers see.
ONPAGE_KEYS = ("schema", "content", "meta")
SPA_ONPAGE_RATIO = 0.15        # earned/max below this on a raw fetch => suspect
SPA_DELTA_POINTS = 10.0        # rendered beats raw by this => confirmed gap


def looks_like_spa(report: AuditReport) -> bool:
    """Heuristic (single raw report): on-page signals nearly absent.

    Meaningful for a requests (no-JS) fetch of a reachable page: when schema +
    content + meta together earn almost nothing, the served HTML is most likely
    an empty JS shell.
    """
    if not report.reachable:
        return False
    cats = {c.key: c for c in report.categories}
    onpage = [cats[k] for k in ONPAGE_KEYS if k in cats]
    if not onpage:
        return False
    earned = sum(c.score for c in onpage)
    total = sum(c.max_score for c in onpage)
    return total > 0 and (earned / total) < SPA_ONPAGE_RATIO


def _summary(report: AuditReport) -> dict:
    return {
        "geo_score": round(report.total_score, 1),
        "grade": report.grade,
        "categories": [
            {
                "key": c.key,
                "name": c.name,
                "score": round(c.score, 1),
                "max_score": c.max_score,
            }
            for c in report.categories
        ],
    }


def build_render_comparison(raw: AuditReport, rendered: AuditReport) -> dict:
    """Compare a raw (no-JS) report against a JS-rendered one.

    Frames the gap as "what AI crawlers see (raw)" vs "what users see
    (rendered)". A large positive delta means the site hides on-page signals
    behind client-side rendering.
    """
    raw_cats = {c.key: c for c in raw.categories}
    deltas = []
    for c in rendered.categories:
        r = raw_cats.get(c.key)
        raw_score = round(r.score, 1) if r else 0.0
        deltas.append(
            {
                "key": c.key,
                "name": c.name,
                "raw": raw_score,
                "rendered": round(c.score, 1),
                "delta": round(c.score - raw_score, 1),
                "max_score": c.max_score,
            }
        )
    delta_total = round(rendered.total_score - raw.total_score, 1)
    return {
        "raw": _summary(raw),
        "rendered": _summary(rendered),
        "delta_total": delta_total,
        "deltas": deltas,
        "spa_suspected": delta_total >= SPA_DELTA_POINTS,
    }
