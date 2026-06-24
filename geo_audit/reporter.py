"""Reporting: human-readable terminal output and JSON export."""

import csv
import json
import sys
from typing import List, Optional

from . import FAIL, OK, WARN
from .scorer import AuditReport, CATEGORY_ORDER

# ANSI colors (auto-disabled when output is not a TTY).
_COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "cyan": "\033[36m",
}

SEVERITY_ICON = {OK: "✓", WARN: "!", FAIL: "✗"}
SEVERITY_COLOR = {OK: "green", WARN: "yellow", FAIL: "red"}


def _supports_color() -> bool:
    return sys.stdout.isatty()


def _c(text: str, color: str, enabled: bool) -> str:
    if not enabled or color not in _COLORS:
        return text
    return f"{_COLORS[color]}{text}{_COLORS['reset']}"


def _score_color(ratio: float) -> str:
    if ratio >= 0.8:
        return "green"
    if ratio >= 0.5:
        return "yellow"
    return "red"


def _bar(ratio: float, width: int = 20) -> str:
    filled = int(round(ratio * width))
    return "█" * filled + "░" * (width - filled)


def render_terminal(report: AuditReport, color: Optional[bool] = None) -> str:
    enabled = _supports_color() if color is None else color
    lines = []

    lines.append("")
    lines.append(_c("═" * 64, "dim", enabled))
    lines.append(_c("  GEO / AIO AUDIT REPORT", "bold", enabled))
    lines.append(_c("═" * 64, "dim", enabled))
    lines.append(f"  URL: {report.final_url}")

    if not report.reachable:
        lines.append("")
        lines.append(_c(f"  ✗ Page unreachable: {report.error}", "red", enabled))
        lines.append(_c("═" * 64, "dim", enabled))
        lines.append("")
        return "\n".join(lines)

    overall_ratio = report.total_score / report.max_score if report.max_score else 0
    score_str = f"{report.total_score:.0f}/{int(report.max_score)}"
    grade_str = f"Grade {report.grade}"
    color_name = _score_color(overall_ratio)
    lines.append("")
    lines.append(
        "  "
        + _c(f"GEO SCORE: {score_str}", "bold", enabled)
        + "  "
        + _c(_bar(overall_ratio, 24), color_name, enabled)
        + "  "
        + _c(grade_str, color_name, enabled)
    )
    lines.append("")
    lines.append(_c("─" * 64, "dim", enabled))

    # Per-category breakdown.
    for cat in report.categories:
        cat_color = _score_color(cat.ratio)
        header = (
            f"  {cat.name:<28} "
            + _c(f"{cat.score:>5.1f}/{int(cat.max_score):<3}", cat_color, enabled)
            + "  "
            + _c(_bar(cat.ratio, 12), cat_color, enabled)
        )
        lines.append(header)
        for f in cat.findings:
            icon = SEVERITY_ICON.get(f.severity, "-")
            icon_c = _c(icon, SEVERITY_COLOR.get(f.severity, "reset"), enabled)
            lines.append(f"      {icon_c} {f.message}")
            if f.recommendation:
                lines.append(
                    "        " + _c(f"→ {f.recommendation}", "cyan", enabled)
                )
        lines.append("")

    lines.append(_c("═" * 64, "dim", enabled))
    lines.append(
        "  " + _summary_line(report)
    )
    lines.append(_c("═" * 64, "dim", enabled))
    lines.append("")
    return "\n".join(lines)


def _summary_line(report: AuditReport) -> str:
    fails = sum(
        1 for c in report.categories for f in c.findings if f.severity == FAIL
    )
    warns = sum(
        1 for c in report.categories for f in c.findings if f.severity == WARN
    )
    return f"Summary: {fails} critical issue(s), {warns} warning(s)."


def print_report(report: AuditReport, color: Optional[bool] = None) -> None:
    print(render_terminal(report, color=color))


def to_json(report: AuditReport, indent: int = 2) -> str:
    return json.dumps(report.to_dict(), indent=indent, ensure_ascii=False)


def export_json(report: AuditReport, path: str, indent: int = 2) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(to_json(report, indent=indent))


def export_csv(reports: List[AuditReport], path: str) -> None:
    """Write a one-row-per-URL summary CSV (used by batch mode)."""
    fieldnames = (
        ["url", "final_url", "reachable", "geo_score", "grade"]
        + [f"{key}_score" for key in CATEGORY_ORDER]
        + ["error"]
    )
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for report in reports:
            cat_scores = {c.key: c.score for c in report.categories}
            row = {
                "url": report.url,
                "final_url": report.final_url,
                "reachable": report.reachable,
                "geo_score": round(report.total_score, 1),
                "grade": report.grade,
                "error": report.error or "",
            }
            for key in CATEGORY_ORDER:
                row[f"{key}_score"] = round(cat_scores.get(key, 0.0), 1)
            writer.writerow(row)
