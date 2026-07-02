"""Manual overrides for findings the crawler could only mark "ambiguous".

Some checks (sitemap, llms.txt, robots.txt) are sidecar-file fetches that a
target's WAF/rate-limiter can block independently of whether the file
actually exists — see the ``*_ambiguous`` fields on ``CrawlResult``. When that
happens, the automated score reflects genuine uncertainty, not a confirmed
absence. A human who checks the URL directly can resolve that uncertainty;
this module applies their answer on top of an already-computed report,
without re-crawling the site.

Each rule undoes exactly the partial-credit/optimistic-default the automated
scorer applied in the ambiguous case, so applying an override is equivalent
to what the score would have been had detection succeeded cleanly.
"""

import copy
from typing import Dict, Optional

from . import OK, WARN, CategoryResult
from .content_analyzer import W_LLMS_PRESENT
from .crawler import AI_BOTS, BOT_MAX_SCORE, PW_SITEMAP, W_SITEMAP
from .scorer import AuditReport, grade_for

# Known override keys -> the category they affect (for validating API input).
OVERRIDABLE_KEYS = {
    "sitemap_exists": "page_speed",
    "llms_txt_exists": "llms_txt",
    "robots_blocked": "bot_access",
}

_PSI_SPEED_NAME = "Sayfa Hızı / Core Web Vitals"


def _find_category(report: AuditReport, key: str) -> Optional[CategoryResult]:
    return next((c for c in report.categories if c.key == key), None)


def _find_finding(category: CategoryResult, override_key: str):
    return next(
        (f for f in category.findings if f.override_key == override_key), None
    )


def _apply_sitemap_exists(report: AuditReport) -> None:
    category = _find_category(report, "page_speed")
    if category is None:
        return
    finding = _find_finding(category, "sitemap_exists")
    if finding is None:
        return
    weight = PW_SITEMAP if category.name == _PSI_SPEED_NAME else W_SITEMAP
    # The ambiguous case already earned half credit; add the other half.
    category.score = min(category.score + weight / 2, category.max_score)
    finding.severity = OK
    finding.message = f"Sitemap manuel olarak doğrulandı: mevcut ({category.name})."
    finding.recommendation = ""


def _apply_llms_txt_exists(report: AuditReport) -> None:
    category = _find_category(report, "llms_txt")
    if category is None:
        return
    finding = _find_finding(category, "llms_txt_exists")
    if finding is None:
        return
    # The ambiguous case earned zero credit; grant the presence baseline
    # (content-quality sub-scores can't be confirmed via a checkbox).
    category.score = min(category.score + W_LLMS_PRESENT, category.max_score)
    finding.severity = OK
    finding.message = (
        "llms.txt manuel olarak doğrulandı: mevcut. "
        "(İçerik kalitesi otomatik değerlendirilemedi.)"
    )
    finding.recommendation = ""


def _apply_robots_blocked(report: AuditReport) -> None:
    category = _find_category(report, "bot_access")
    if category is None:
        return
    finding = _find_finding(category, "robots_blocked")
    if finding is None:
        return
    per_bot = BOT_MAX_SCORE / len(AI_BOTS)
    category.score = max(category.score - per_bot, 0.0)
    finding.severity = WARN
    finding.message = (
        "robots.txt manuel olarak incelendi: bir veya daha fazla AI botu "
        "engelleniyor. (Kesin etki bilinmediği için bir bot payı kadar puan "
        "düşürüldü — tam etki için robots.txt'yi inceleyip Disallow "
        "kurallarını kaldırın.)"
    )
    finding.recommendation = (
        "Engellenen bot(lar) için Disallow kuralını kaldırın."
    )


_HANDLERS = {
    "sitemap_exists": _apply_sitemap_exists,
    "llms_txt_exists": _apply_llms_txt_exists,
    "robots_blocked": _apply_robots_blocked,
}


def apply_overrides(report: AuditReport, overrides: Dict[str, bool]) -> AuditReport:
    """Return a new report with confirmed (``True``) overrides applied.

    ``report`` is never mutated — callers keep the automated baseline
    (``Audit.report_json``) untouched and re-apply the current override set
    fresh every time, so toggling a checkbox off is just omitting its key.
    """
    if not overrides:
        return report
    adjusted = copy.deepcopy(report)
    for key, handler in _HANDLERS.items():
        if overrides.get(key) is True:
            handler(adjusted)
    adjusted.total_score = sum(c.score for c in adjusted.categories)
    adjusted.grade = grade_for(adjusted.total_score)
    return adjusted
