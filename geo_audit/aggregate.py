"""Aggregate many single-page AuditReports into one list-level summary.

Pure and side-effect free (like scorer/reporter): the web layer runs each URL
through the normal engine, then calls ``aggregate_reports`` to produce an
average score, per-category averages, per-page rows, and the most common gaps
across the set — the raw material for a combined "strategy" report.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import List

from . import FAIL, WARN
from .scorer import AuditReport, CATEGORY_ORDER, grade_for


@dataclass
class AggregateReport:
    """A list audit: the rolled-up view over several page reports."""

    url_count: int
    reachable_count: int
    avg_score: float
    grade: str
    # One row per CATEGORY_ORDER key: averaged over reachable pages.
    category_averages: List[dict] = field(default_factory=list)
    # One row per audited URL (order preserved).
    pages: List[dict] = field(default_factory=list)
    # Most common critical/warning findings across pages (the shared gaps that
    # a site-wide fix would address), most frequent first.
    top_gaps: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scope": "list",
            "url_count": self.url_count,
            "reachable_count": self.reachable_count,
            "avg_score": round(self.avg_score, 1),
            "grade": self.grade,
            "category_averages": self.category_averages,
            "pages": self.pages,
            "top_gaps": self.top_gaps,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AggregateReport":
        return cls(
            url_count=data["url_count"],
            reachable_count=data["reachable_count"],
            avg_score=data["avg_score"],
            grade=data["grade"],
            category_averages=data.get("category_averages", []),
            pages=data.get("pages", []),
            top_gaps=data.get("top_gaps", []),
        )


def _page_row(report: AuditReport) -> dict:
    return {
        "url": report.url,
        "final_url": report.final_url,
        "reachable": report.reachable,
        "geo_score": round(report.total_score, 1) if report.reachable else None,
        "grade": report.grade if report.reachable else None,
        "error": report.error,
    }


def _category_averages(reachable: List[AuditReport]) -> List[dict]:
    rows: List[dict] = []
    # Use the first reachable report to resolve human-readable category names
    # (all reports share the same CATEGORY_ORDER and names).
    names = {}
    max_scores = {}
    for r in reachable:
        for c in r.categories:
            names.setdefault(c.key, c.name)
            max_scores.setdefault(c.key, c.max_score)

    for key in CATEGORY_ORDER:
        scores = [
            c.score
            for r in reachable
            for c in r.categories
            if c.key == key
        ]
        if not scores:
            continue
        avg = sum(scores) / len(scores)
        max_score = max_scores.get(key, 0.0)
        rows.append(
            {
                "key": key,
                "name": names.get(key, key),
                "avg_score": round(avg, 1),
                "max_score": max_score,
                "avg_ratio": round(avg / max_score, 4) if max_score else 0.0,
            }
        )
    return rows


def _top_gaps(reachable: List[AuditReport], limit: int = 8) -> List[dict]:
    """Count FAIL/WARN findings shared across pages, criticals weighted first."""
    counter: Counter = Counter()
    meta: dict = {}
    for r in reachable:
        # De-dupe within a page so a finding repeated on one page counts once.
        seen = set()
        for cat in r.categories:
            for f in cat.findings:
                if f.severity not in (FAIL, WARN):
                    continue
                key = (cat.key, f.message)
                if key in seen:
                    continue
                seen.add(key)
                counter[key] += 1
                meta.setdefault(
                    key,
                    {
                        "category": cat.name,
                        "message": f.message,
                        "recommendation": f.recommendation,
                        "severity": f.severity,
                    },
                )

    def sort_key(item):
        (cat_key, _msg), count = item
        sev = meta[(cat_key, _msg)]["severity"]
        # Criticals before warnings; then by how many pages share it.
        return (0 if sev == FAIL else 1, -count)

    ordered = sorted(counter.items(), key=sort_key)
    gaps = []
    for (cat_key, msg), count in ordered[:limit]:
        info = meta[(cat_key, msg)]
        gaps.append({**info, "page_count": count})
    return gaps


def aggregate_reports(reports: List[AuditReport]) -> AggregateReport:
    """Roll up per-page reports into a single list-level summary.

    ``avg_score`` and category averages are computed over *reachable* pages
    only (an unreachable URL shouldn't drag the mean toward zero as if it
    scored badly — it simply wasn't measured); ``url_count`` still reflects
    every URL submitted.
    """
    reachable = [r for r in reports if r.reachable]
    avg_score = (
        sum(r.total_score for r in reachable) / len(reachable) if reachable else 0.0
    )
    return AggregateReport(
        url_count=len(reports),
        reachable_count=len(reachable),
        avg_score=avg_score,
        grade=grade_for(avg_score) if reachable else "F",
        category_averages=_category_averages(reachable),
        pages=[_page_row(r) for r in reports],
        top_gaps=_top_gaps(reachable),
    )
