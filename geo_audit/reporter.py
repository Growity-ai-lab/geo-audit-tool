"""Reporting: terminal output, JSON/CSV export, and a client-facing HTML report."""

import csv
import html as _html
import json
import sys
from datetime import datetime
from typing import List, Optional

from . import FAIL, OK, WARN
from .scorer import AuditReport, CATEGORY_ORDER, grade_description

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
    lines.append(_c("  GEO / AIO HAZIRLIK RAPORU", "bold", enabled))
    lines.append(_c("═" * 64, "dim", enabled))
    lines.append(f"  URL: {report.final_url}")

    if not report.reachable:
        lines.append("")
        lines.append(_c(f"  ✗ Sayfaya erişilemedi: {report.error}", "red", enabled))
        lines.append(_c("═" * 64, "dim", enabled))
        lines.append("")
        return "\n".join(lines)

    overall_ratio = report.total_score / report.max_score if report.max_score else 0
    score_str = f"{report.total_score:.0f}/{int(report.max_score)}"
    grade_str = f"Not {report.grade}"
    color_name = _score_color(overall_ratio)
    lines.append("")
    lines.append(
        "  "
        + _c(f"GEO SKORU: {score_str}", "bold", enabled)
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
    return f"Özet: {fails} kritik sorun, {warns} uyarı."


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


# --------------------------------------------------------------------------- #
# Client-facing HTML report (Turkish, brandable, print/PDF friendly).
# --------------------------------------------------------------------------- #

SEVERITY_LABEL = {OK: "Başarılı", WARN: "Uyarı", FAIL: "Kritik"}
_GRADE_COLOR = {"A": "#16a34a", "B": "#16a34a", "C": "#d97706",
                "D": "#d97706", "E": "#dc2626", "F": "#dc2626"}


def _esc(text: str) -> str:
    return _html.escape(str(text), quote=True)


def _hue(ratio: float) -> str:
    if ratio >= 0.8:
        return "#16a34a"  # green
    if ratio >= 0.5:
        return "#d97706"  # amber
    return "#dc2626"      # red


def _priority_actions(report: AuditReport, limit: int = 5) -> List[tuple]:
    """Top recommendations, criticals first, with their category name."""
    items = []
    for cat in report.categories:
        for f in cat.findings:
            if f.recommendation and f.severity in (FAIL, WARN):
                items.append((f.severity, cat.name, f.recommendation))
    # FAIL before WARN, preserve discovery order otherwise.
    items.sort(key=lambda x: 0 if x[0] == FAIL else 1)
    return items[:limit]


def render_html(
    report: AuditReport,
    brand: str = "Growity",
    client: str = "",
    generated_at: Optional[str] = None,
) -> str:
    when = generated_at or datetime.now().strftime("%d.%m.%Y %H:%M")
    client_line = f"{_esc(client)} · " if client else ""
    grade = report.grade if report.reachable else "F"
    grade_color = _GRADE_COLOR.get(grade, "#dc2626")

    if not report.reachable:
        body = f"""
        <div class="card error">
          <h2>Sayfaya erişilemedi</h2>
          <p>{_esc(report.error or 'Bilinmeyen hata')}</p>
        </div>"""
        return _html_shell(brand, client_line, report.final_url, when, body)

    ratio = report.total_score / report.max_score if report.max_score else 0
    fails = sum(1 for c in report.categories for f in c.findings if f.severity == FAIL)
    warns = sum(1 for c in report.categories for f in c.findings if f.severity == WARN)

    # Score hero (conic-gradient gauge).
    deg = round(ratio * 360)
    hero = f"""
    <section class="hero">
      <div class="gauge" style="background:conic-gradient({grade_color} {deg}deg, #e5e7eb 0deg);">
        <div class="gauge-inner">
          <div class="score">{report.total_score:.0f}<span class="of">/100</span></div>
          <div class="grade" style="color:{grade_color}">Not {grade}</div>
        </div>
      </div>
      <div class="hero-text">
        <h2>Genel GEO Skoru</h2>
        <p class="verdict">{_esc(grade_description(report.total_score))}</p>
        <div class="pills">
          <span class="pill pill-fail">{fails} kritik sorun</span>
          <span class="pill pill-warn">{warns} uyarı</span>
        </div>
      </div>
    </section>"""

    # Priority actions.
    actions = _priority_actions(report)
    if actions:
        rows = "".join(
            f"""<li><span class="tag tag-{'fail' if sev==FAIL else 'warn'}">{SEVERITY_LABEL[sev]}</span>
                <span class="act-cat">{_esc(cat)}</span>
                <span class="act-rec">{_esc(rec)}</span></li>"""
            for sev, cat, rec in actions
        )
        priority = f"""
        <section class="card">
          <h2>Öncelikli Aksiyonlar</h2>
          <ol class="actions">{rows}</ol>
        </section>"""
    else:
        priority = ""

    # Category breakdown.
    cat_blocks = []
    for cat in report.categories:
        c_ratio = cat.ratio
        color = _hue(c_ratio)
        findings_html = ""
        for f in cat.findings:
            cls = {OK: "ok", WARN: "warn", FAIL: "fail"}[f.severity]
            icon = {OK: "✓", WARN: "!", FAIL: "✗"}[f.severity]
            rec = (
                f'<div class="rec">→ {_esc(f.recommendation)}</div>'
                if f.recommendation else ""
            )
            findings_html += f"""
            <li class="finding {cls}">
              <span class="ficon">{icon}</span>
              <div><div class="fmsg">{_esc(f.message)}</div>{rec}</div>
            </li>"""
        cat_blocks.append(f"""
        <section class="card category">
          <div class="cat-head">
            <h3>{_esc(cat.name)}</h3>
            <div class="cat-score" style="color:{color}">{cat.score:.1f}<span>/{int(cat.max_score)}</span></div>
          </div>
          <div class="bar"><div class="bar-fill" style="width:{c_ratio*100:.0f}%;background:{color}"></div></div>
          <ul class="findings">{findings_html}</ul>
        </section>""")

    body = hero + priority + "".join(cat_blocks)
    return _html_shell(brand, client_line, report.final_url, when, body)


def _html_shell(brand, client_line, url, when, body) -> str:
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GEO / AIO Raporu — {_esc(url)}</title>
<style>
  :root {{ --brand:#4f46e5; --ink:#0f172a; --muted:#64748b; --line:#e5e7eb; --bg:#f8fafc; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
          color:var(--ink); background:var(--bg); line-height:1.55; }}
  .wrap {{ max-width:880px; margin:0 auto; padding:32px 24px 64px; }}
  header.top {{ display:flex; justify-content:space-between; align-items:flex-end;
               border-bottom:3px solid var(--brand); padding-bottom:16px; margin-bottom:28px; }}
  .brand {{ font-size:24px; font-weight:800; letter-spacing:-.02em; color:var(--brand); }}
  .brand small {{ display:block; font-size:12px; font-weight:600; color:var(--muted); letter-spacing:.04em; }}
  .meta {{ text-align:right; font-size:13px; color:var(--muted); }}
  .meta .u {{ color:var(--ink); font-weight:600; word-break:break-all; }}
  h2 {{ font-size:18px; margin:0 0 12px; }}
  h3 {{ font-size:16px; margin:0; }}
  .hero {{ display:flex; gap:28px; align-items:center; background:#fff; border:1px solid var(--line);
           border-radius:16px; padding:28px; margin-bottom:24px; }}
  .gauge {{ width:150px; height:150px; border-radius:50%; flex:none; display:flex;
            align-items:center; justify-content:center; }}
  .gauge-inner {{ width:116px; height:116px; background:#fff; border-radius:50%;
                  display:flex; flex-direction:column; align-items:center; justify-content:center; }}
  .score {{ font-size:40px; font-weight:800; line-height:1; }}
  .score .of {{ font-size:16px; color:var(--muted); font-weight:600; }}
  .grade {{ font-size:15px; font-weight:700; margin-top:4px; }}
  .verdict {{ margin:.2em 0 1em; color:var(--muted); }}
  .pills {{ display:flex; gap:10px; }}
  .pill {{ font-size:13px; font-weight:600; padding:5px 12px; border-radius:999px; }}
  .pill-fail {{ background:#fee2e2; color:#b91c1c; }}
  .pill-warn {{ background:#fef3c7; color:#b45309; }}
  .card {{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:22px; margin-bottom:18px; }}
  .card.error {{ border-color:#fecaca; background:#fff1f2; }}
  .actions {{ margin:0; padding-left:20px; }}
  .actions li {{ margin:10px 0; }}
  .tag {{ font-size:11px; font-weight:700; padding:2px 8px; border-radius:6px; margin-right:8px; }}
  .tag-fail {{ background:#fee2e2; color:#b91c1c; }}
  .tag-warn {{ background:#fef3c7; color:#b45309; }}
  .act-cat {{ font-weight:600; }}
  .act-rec {{ display:block; color:var(--muted); margin-top:2px; }}
  .cat-head {{ display:flex; justify-content:space-between; align-items:baseline; margin-bottom:10px; }}
  .cat-score {{ font-size:22px; font-weight:800; }}
  .cat-score span {{ font-size:13px; color:var(--muted); font-weight:600; }}
  .bar {{ height:8px; background:#eef2f7; border-radius:999px; overflow:hidden; margin-bottom:14px; }}
  .bar-fill {{ height:100%; border-radius:999px; }}
  .findings {{ list-style:none; margin:0; padding:0; }}
  .finding {{ display:flex; gap:10px; padding:8px 0; border-top:1px solid var(--line); }}
  .finding:first-child {{ border-top:none; }}
  .ficon {{ flex:none; width:22px; height:22px; border-radius:50%; text-align:center;
            line-height:22px; font-weight:700; font-size:13px; color:#fff; }}
  .finding.ok .ficon {{ background:#16a34a; }}
  .finding.warn .ficon {{ background:#d97706; }}
  .finding.fail .ficon {{ background:#dc2626; }}
  .fmsg {{ font-size:14px; }}
  .rec {{ font-size:13px; color:var(--muted); margin-top:2px; }}
  footer {{ margin-top:32px; padding-top:16px; border-top:1px solid var(--line);
            font-size:12px; color:var(--muted); text-align:center; }}
  @media print {{
    body {{ background:#fff; }}
    .wrap {{ max-width:100%; padding:0; }}
    .card, .hero {{ break-inside:avoid; border-color:#d1d5db; }}
    header.top {{ position:running(header); }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    <header class="top">
      <div class="brand">{_esc(brand)}<small>GEO / AIO HAZIRLIK RAPORU</small></div>
      <div class="meta"><div class="u">{client_line}{_esc(url)}</div><div>{_esc(when)}</div></div>
    </header>
    {body}
    <footer>
      Bu rapor {_esc(brand)} GEO/AIO Audit aracı ile üretilmiştir · {_esc(when)}<br>
      Skorlama: AI Bot Erişimi (25) · llms.txt (10) · Schema (25) · İçerik (20) · Meta (10) · Hız/Taranabilirlik (10)
    </footer>
  </div>
</body>
</html>"""


def export_html(
    report: AuditReport,
    path: str,
    brand: str = "Growity",
    client: str = "",
) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_html(report, brand=brand, client=client))
