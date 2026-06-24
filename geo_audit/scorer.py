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

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "reachable": self.reachable,
            "error": self.error,
            "geo_score": round(self.total_score, 1),
            "max_score": self.max_score,
            "grade": self.grade,
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
            crawl_result.llms_txt_found, crawl_result.llms_txt_url
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
