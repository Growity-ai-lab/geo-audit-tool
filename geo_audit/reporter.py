"""Reporting: terminal output, JSON/CSV export, and a client-facing HTML report."""

import base64
import csv
import html as _html
import json
import mimetypes
import os
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
    lines.append("  " + _summary_line(report))
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

# Category accent icons keyed by CategoryResult.key.
CATEGORY_ICON = {
    "bot_access": "🤖",
    "llms_txt": "📄",
    "schema": "🏷️",
    "content": "📝",
    "meta": "🔖",
    "page_speed": "⚡",
}

# Built-in Growity wordmark (used when no --logo file is supplied).
DEFAULT_LOGO_SVG = (
    '<svg class="logo" viewBox="0 0 232 52" xmlns="http://www.w3.org/2000/svg" '
    'role="img" aria-label="growity">'
    '<text x="0" y="40" font-family="\'Trebuchet MS\',Verdana,Geneva,sans-serif" '
    'font-size="46" font-weight="800" letter-spacing="-3" fill="#2f2f33">growity</text>'
    '<circle cx="214" cy="13" r="8" fill="none" stroke="#7c3aed" stroke-width="6"/>'
    "</svg>"
)


def _esc(text: str) -> str:
    return _html.escape(str(text), quote=True)


def _hue(ratio: float) -> str:
    if ratio >= 0.8:
        return "#16a34a"  # green
    if ratio >= 0.5:
        return "#d97706"  # amber
    return "#dc2626"      # red


def _embed_image(path: str) -> Optional[str]:
    """Return a base64 data-URI for an image file, or None if unavailable."""
    if not path or not os.path.isfile(path):
        return None
    if path.lower().endswith(".svg"):
        mime = "image/svg+xml"
    else:
        mime, _ = mimetypes.guess_type(path)
        mime = mime or "image/png"
    try:
        with open(path, "rb") as fh:
            data = base64.b64encode(fh.read()).decode("ascii")
    except OSError:
        return None
    return f"data:{mime};base64,{data}"


def _logo_markup(brand: str, logo_path: str = "") -> str:
    """Brand logo as an <img> data-URI, else the built-in Growity wordmark."""
    uri = _embed_image(logo_path)
    if uri:
        return f'<img class="logo" src="{uri}" alt="{_esc(brand)}">'
    return DEFAULT_LOGO_SVG


def _client_logo_markup(client: str, logo_path: str = "") -> str:
    """Client logo chip for the cover panel (empty string if none)."""
    uri = _embed_image(logo_path)
    if not uri:
        return ""
    return f'<div class="client-logo"><img src="{uri}" alt="{_esc(client)}"></div>'


def _priority_actions(report: AuditReport, limit: int = 6) -> List[tuple]:
    """Top recommendations, criticals first, with their category name."""
    items = []
    for cat in report.categories:
        for f in cat.findings:
            if f.recommendation and f.severity in (FAIL, WARN):
                items.append((f.severity, cat.name, f.recommendation))
    items.sort(key=lambda x: 0 if x[0] == FAIL else 1)
    return items[:limit]


def render_html(
    report: AuditReport,
    brand: str = "Growity",
    client: str = "",
    logo: str = "",
    client_logo: str = "",
    generated_at: Optional[str] = None,
) -> str:
    when = generated_at or datetime.now().strftime("%d.%m.%Y %H:%M")
    logo_html = _logo_markup(brand, logo)
    client_logo_html = _client_logo_markup(client, client_logo)
    title = client or report.final_url

    if not report.reachable:
        body = f"""
        <section class="cover cover-error">
          <div class="cover-l">
            <div class="eyebrow">GEO / AIO HAZIRLIK RAPORU</div>
            {client_logo_html}
            <h1>{_esc(title)}</h1>
            <div class="cover-url">{_esc(report.final_url)}</div>
          </div>
        </section>
        <section class="card error">
          <h2>Sayfaya erişilemedi</h2>
          <p>{_esc(report.error or 'Bilinmeyen hata')}</p>
        </section>"""
        return _html_shell(logo_html, brand, report.final_url, when, body)

    ratio = report.total_score / report.max_score if report.max_score else 0
    grade = report.grade
    grade_color = _hue(ratio)
    deg = round(ratio * 360)
    fails = sum(1 for c in report.categories for f in c.findings if f.severity == FAIL)
    warns = sum(1 for c in report.categories for f in c.findings if f.severity == WARN)
    oks = sum(1 for c in report.categories for f in c.findings if f.severity == OK)

    # --- Cover: brand-gradient panel with gauge -------------------------
    cover = f"""
    <section class="cover">
      <div class="cover-l">
        <div class="eyebrow">GEO / AIO HAZIRLIK RAPORU</div>
        {client_logo_html}
        <h1>{_esc(title)}</h1>
        <a class="cover-url">{_esc(report.final_url)}</a>
        <div class="cover-meta">Rapor tarihi: {_esc(when)}</div>
      </div>
      <div class="cover-r">
        <div class="gauge" style="background:conic-gradient(#ffffff {deg}deg, rgba(255,255,255,.22) 0deg);">
          <div class="gauge-inner">
            <div class="score" style="color:{grade_color}">{report.total_score:.0f}<span class="of">/100</span></div>
            <div class="grade">Not {grade}</div>
          </div>
        </div>
      </div>
    </section>"""

    # --- Verdict + stat strip -------------------------------------------
    summary = f"""
    <section class="summary">
      <p class="verdict">{_esc(grade_description(report.total_score))}</p>
      <div class="stats">
        <div class="stat stat-fail"><b>{fails}</b><span>kritik sorun</span></div>
        <div class="stat stat-warn"><b>{warns}</b><span>uyarı</span></div>
        <div class="stat stat-ok"><b>{oks}</b><span>başarılı kontrol</span></div>
      </div>
    </section>"""

    explain = _explainer_block(report.grade)

    # --- Priority actions ------------------------------------------------
    actions = _priority_actions(report)
    if actions:
        rows = "".join(
            f"""<li class="{'pa-fail' if sev==FAIL else 'pa-warn'}">
                  <span class="pa-tag">{SEVERITY_LABEL[sev]}</span>
                  <div><span class="pa-cat">{_esc(cat)}</span>
                  <span class="pa-rec">{_esc(rec)}</span></div>
                </li>"""
            for sev, cat, rec in actions
        )
        priority = f"""
        <section class="card">
          <h2><span class="h2-accent"></span>Öncelikli Aksiyonlar</h2>
          <ol class="actions">{rows}</ol>
        </section>"""
    else:
        priority = ""

    # --- Category breakdown ---------------------------------------------
    cat_blocks = ['<h2 class="section-title"><span class="h2-accent"></span>Kategori Detayları</h2>']
    for cat in report.categories:
        c_ratio = cat.ratio
        color = _hue(c_ratio)
        icon = CATEGORY_ICON.get(cat.key, "•")
        findings_html = ""
        for f in cat.findings:
            cls = {OK: "ok", WARN: "warn", FAIL: "fail"}[f.severity]
            ic = {OK: "✓", WARN: "!", FAIL: "✗"}[f.severity]
            rec = (
                f'<div class="rec">{_esc(f.recommendation)}</div>'
                if f.recommendation else ""
            )
            findings_html += f"""
            <li class="finding {cls}">
              <span class="ficon">{ic}</span>
              <div><div class="fmsg">{_esc(f.message)}</div>{rec}</div>
            </li>"""
        cat_blocks.append(f"""
        <section class="card category" style="border-left:4px solid {color}">
          <div class="cat-head">
            <div class="cat-title"><span class="cat-icon">{icon}</span><h3>{_esc(cat.name)}</h3></div>
            <div class="cat-score" style="color:{color}">{cat.score:.1f}<span>/{int(cat.max_score)}</span></div>
          </div>
          <div class="bar"><div class="bar-fill" style="width:{c_ratio*100:.0f}%;background:{color}"></div></div>
          <ul class="findings">{findings_html}</ul>
        </section>""")

    offering = _offering_block(brand)

    gap = _render_gap_block(report)
    body = cover + summary + gap + explain + priority + "".join(cat_blocks) + offering
    return _html_shell(logo_html, brand, report.final_url, when, body)


# Grade bands shown in the explainer legend.
_GRADE_BANDS = [
    ("A", "90-100", "Mükemmel"),
    ("B", "80-89", "İyi"),
    ("C", "70-79", "Orta-iyi"),
    ("D", "60-69", "Orta"),
    ("E", "50-59", "Zayıf"),
    ("F", "0-49", "Kritik"),
]


def _render_gap_block(report: AuditReport) -> str:
    """Render the raw-vs-rendered comparison, or a SPA warning, or nothing."""
    comp = report.render_comparison
    if comp:
        raw, ren = comp["raw"], comp["rendered"]
        rows = ""
        for d in comp["deltas"]:
            if abs(d["delta"]) < 0.05:
                continue
            up = d["delta"] > 0
            rows += (
                f"<tr><td>{_esc(d['name'])}</td><td>{d['raw']:.1f}</td>"
                f"<td>{d['rendered']:.1f}</td>"
                f"<td class='dl' style='color:{'#15803d' if up else '#b91c1c'}'>"
                f"{'▲' if up else '▼'} {abs(d['delta']):.1f}</td></tr>"
            )
        if not rows:
            rows = "<tr><td colspan='4'>Render ile anlamlı fark bulunmadı.</td></tr>"
        return f"""
    <section class="card gap">
      <h2><span class="h2-accent"></span>AI'ın Gördüğü vs Kullanıcının Gördüğü</h2>
      <p class="gap-lead">Bu site içeriğinin bir kısmını tarayıcıda JavaScript ile
      üretiyor. AI tarayıcıları (GPTBot, ClaudeBot, PerplexityBot…) çoğunlukla
      JavaScript çalıştırmaz; bu yüzden aşağıdaki <b>Ham HTML</b> sütunu, bu
      motorların pratikte gördüğü puandır.</p>
      <div class="gap-scores">
        <div class="gap-score"><span>Ham HTML — AI motorları</span><b style="color:{_hue(raw['geo_score']/100)}">{raw['geo_score']:.0f} <i>{raw['grade']}</i></b></div>
        <div class="gap-arrow">+{comp['delta_total']:.0f}</div>
        <div class="gap-score"><span>JS sonrası — kullanıcı</span><b style="color:{_hue(ren['geo_score']/100)}">{ren['geo_score']:.0f} <i>{ren['grade']}</i></b></div>
      </div>
      <table class="deltas"><thead><tr><th>Kategori</th><th>Ham</th><th>JS</th><th>Fark</th></tr></thead><tbody>{rows}</tbody></table>
      <p class="gap-fix">Öneri: başlık, meta, schema ve ana içeriği <b>sunucu
      tarafında üretin</b> (SSR / prerender) — böylece AI motorları da kullanıcının
      gördüğü içeriği görür.</p>
    </section>"""
    if report.spa_suspected:
        return """
    <section class="card gap-warn">
      <h2><span class="h2-accent"></span>⚠️ Olası SPA — içerik JavaScript ile üretiliyor olabilir</h2>
      <p>Sayfanın sunucudan dönen HTML'inde başlık, meta ve içerik sinyalleri
      neredeyse yok; içerik büyük olasılıkla tarayıcıda JavaScript ile yükleniyor.
      <b>AI tarayıcıları bunu çoğunlukla göremez.</b> Aracı "JavaScript ile render
      et" seçeneğiyle tekrar çalıştırın; kalıcı çözüm için kritik içeriği sunucu
      tarafında üretin (SSR / prerender).</p>
    </section>"""
    return ""


def _explainer_block(grade: str) -> str:
    bands = "".join(
        f'<div class="band{" band-on" if g == grade else ""}">'
        f'<b>{g}</b><span>{rng}</span><span>{lbl}</span></div>'
        for g, rng, lbl in _GRADE_BANDS
    )
    return f"""
    <section class="card explain">
      <h2><span class="h2-accent"></span>Bu Rapor Ne Anlama Geliyor?</h2>
      <p>Arama artık yalnızca Google'da değil. ChatGPT, Claude, Perplexity ve
      Google AI Overviews gibi yapay zekâ motorları kullanıcıların sorularını
      doğrudan yanıtlıyor ve kaynak gösteriyor. <b>GEO (Generative Engine
      Optimization)</b>, markanızın bu yanıtlarda görünür ve alıntılanabilir
      olmasını sağlar. Bu rapor, sitenizin yapay zekâ motorlarına ne kadar hazır
      olduğunu 6 kategoride 100 puan üzerinden ölçer; düşük puanlı alanlar en
      yüksek getirili iyileştirme fırsatlarınızı gösterir.</p>
      <div class="bands">{bands}</div>
    </section>"""


def _offering_block(brand: str) -> str:
    items = [
        "AI tarayıcı erişimi: robots.txt ve llms.txt yapılandırması",
        "Schema.org işaretlemesi (FAQ, Organization, HowTo, Article)",
        "Önce-cevap (answer-first) içerik mimarisi ve başlık hiyerarşisi",
        "Meta sinyalleri, Open Graph ve varlık (entity) optimizasyonu",
        "Teknik performans ve taranabilirlik iyileştirmeleri",
        "Aylık GEO görünürlük takibi ve raporlama",
    ]
    lis = "".join(f"<li>{_esc(i)}</li>" for i in items)
    return f"""
    <section class="card cta">
      <h2><span class="h2-accent"></span>{_esc(brand)} ile Sonraki Adımlar</h2>
      <p>Yukarıdaki bulguların her biri somut bir iyileştirme kalemine karşılık
      gelir. {_esc(brand)} olarak sitenizi yapay zekâ arama motorlarında
      görünür ve alıntılanabilir hâle getirmek için uçtan uca destek sunuyoruz:</p>
      <ul class="offer">{lis}</ul>
    </section>"""


def _html_shell(logo_html, brand, url, when, body) -> str:
    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GEO / AIO Raporu — {_esc(url)}</title>
<style>
  :root {{
    --brand:#6d28d9; --brand-deep:#4c1d95; --ring:#7c3aed; --tint:#f5f3ff;
    --ink:#2f2f33; --muted:#6b7280; --line:#e7e3f3; --bg:#faf9fe;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
          color:var(--ink); background:var(--bg); line-height:1.55; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  .wrap {{ max-width:900px; margin:0 auto; padding:28px 24px 64px; }}
  header.top {{ display:flex; justify-content:space-between; align-items:center;
               padding-bottom:16px; margin-bottom:22px; border-bottom:1px solid var(--line); }}
  .logo {{ height:34px; width:auto; display:block; }}
  .top-label {{ text-align:right; font-size:11px; font-weight:700; letter-spacing:.14em;
                color:var(--muted); text-transform:uppercase; }}
  h1 {{ font-size:30px; line-height:1.15; margin:6px 0 8px; letter-spacing:-.02em; }}
  h2 {{ font-size:17px; margin:0 0 14px; display:flex; align-items:center; gap:10px; }}
  h3 {{ font-size:15.5px; margin:0; }}
  .h2-accent {{ width:6px; height:18px; border-radius:3px; background:var(--brand); display:inline-block; }}
  .section-title {{ font-size:17px; margin:26px 4px 14px; display:flex; align-items:center; gap:10px; }}

  /* Cover */
  .cover {{ display:flex; justify-content:space-between; align-items:center; gap:24px;
            background:linear-gradient(135deg,var(--brand),var(--brand-deep)); color:#fff;
            border-radius:20px; padding:34px 36px; margin-bottom:18px;
            box-shadow:0 18px 40px -22px rgba(76,29,149,.7); }}
  .cover-error {{ background:linear-gradient(135deg,#9f1239,#7f1d1d); }}
  .eyebrow {{ font-size:11px; font-weight:700; letter-spacing:.16em; text-transform:uppercase; opacity:.85; }}
  .client-logo {{ display:inline-block; background:#fff; border-radius:10px; padding:8px 12px;
                  margin:12px 0 4px; box-shadow:0 6px 18px -8px rgba(0,0,0,.4); }}
  .client-logo img {{ height:30px; width:auto; display:block; }}
  .cover-url {{ display:inline-block; font-size:14px; opacity:.92; word-break:break-all; }}
  .cover-meta {{ font-size:12.5px; opacity:.8; margin-top:10px; }}
  .gauge {{ width:158px; height:158px; border-radius:50%; flex:none; display:flex;
            align-items:center; justify-content:center; box-shadow:0 8px 24px -8px rgba(0,0,0,.35); }}
  .gauge-inner {{ width:122px; height:122px; background:#fff; border-radius:50%;
                  display:flex; flex-direction:column; align-items:center; justify-content:center; }}
  .score {{ font-size:44px; font-weight:800; line-height:1; }}
  .score .of {{ font-size:16px; color:var(--muted); font-weight:700; }}
  .grade {{ font-size:14px; font-weight:800; color:var(--ink); margin-top:2px; }}

  /* Summary strip */
  .summary {{ display:flex; justify-content:space-between; align-items:center; gap:20px;
              background:#fff; border:1px solid var(--line); border-radius:16px;
              padding:18px 22px; margin-bottom:18px; }}
  .verdict {{ margin:0; font-size:15px; font-weight:600; max-width:54%; }}
  .stats {{ display:flex; gap:10px; }}
  .stat {{ text-align:center; border-radius:12px; padding:8px 16px; min-width:78px; }}
  .stat b {{ display:block; font-size:24px; font-weight:800; line-height:1; }}
  .stat span {{ font-size:11px; font-weight:600; }}
  .stat-fail {{ background:#fee2e2; color:#b91c1c; }}
  .stat-warn {{ background:#fef3c7; color:#b45309; }}
  .stat-ok {{ background:#dcfce7; color:#15803d; }}

  /* Cards */
  .card {{ background:#fff; border:1px solid var(--line); border-radius:16px; padding:22px 24px; margin-bottom:16px;
           box-shadow:0 1px 2px rgba(16,24,40,.04); }}
  .card.error {{ border-color:#fecaca; background:#fff1f2; }}

  /* Priority actions */
  .actions {{ list-style:none; margin:0; padding:0; counter-reset:pa; }}
  .actions li {{ display:flex; gap:12px; align-items:flex-start; padding:12px 0; border-top:1px solid var(--line); }}
  .actions li:first-child {{ border-top:none; }}
  .pa-tag {{ flex:none; font-size:11px; font-weight:800; padding:3px 9px; border-radius:7px; }}
  .pa-fail .pa-tag {{ background:#fee2e2; color:#b91c1c; }}
  .pa-warn .pa-tag {{ background:#fef3c7; color:#b45309; }}
  .pa-cat {{ font-weight:700; }}
  .pa-rec {{ display:block; color:var(--muted); margin-top:2px; font-size:14px; }}

  /* Category */
  .cat-head {{ display:flex; justify-content:space-between; align-items:center; margin-bottom:12px; }}
  .cat-title {{ display:flex; align-items:center; gap:10px; }}
  .cat-icon {{ width:34px; height:34px; border-radius:10px; background:var(--tint);
               display:inline-flex; align-items:center; justify-content:center; font-size:18px; }}
  .cat-score {{ font-size:23px; font-weight:800; }}
  .cat-score span {{ font-size:13px; color:var(--muted); font-weight:700; }}
  .bar {{ height:9px; background:#eef0f5; border-radius:999px; overflow:hidden; margin-bottom:16px; }}
  .bar-fill {{ height:100%; border-radius:999px; }}
  .findings {{ list-style:none; margin:0; padding:0; }}
  .finding {{ display:flex; gap:11px; padding:9px 0; border-top:1px solid var(--line); }}
  .finding:first-child {{ border-top:none; }}
  .ficon {{ flex:none; width:22px; height:22px; border-radius:50%; text-align:center;
            line-height:22px; font-weight:800; font-size:13px; color:#fff; }}
  .finding.ok .ficon {{ background:#16a34a; }}
  .finding.warn .ficon {{ background:#d97706; }}
  .finding.fail .ficon {{ background:#dc2626; }}
  .fmsg {{ font-size:14px; }}
  .rec {{ font-size:13px; color:var(--muted); margin-top:3px; padding-left:12px; border-left:2px solid var(--line); }}

  /* Explainer + bands */
  .explain p {{ margin:0 0 16px; font-size:14px; }}
  .bands {{ display:grid; grid-template-columns:repeat(6,1fr); gap:8px; }}
  .band {{ text-align:center; border:1px solid var(--line); border-radius:10px; padding:8px 4px; background:#fff; }}
  .band b {{ display:block; font-size:18px; font-weight:800; }}
  .band span {{ display:block; font-size:10.5px; color:var(--muted); }}
  .band-on {{ background:var(--tint); border-color:var(--brand); box-shadow:0 0 0 2px var(--brand) inset; }}
  .band-on b {{ color:var(--brand); }}

  /* CTA / offering */
  .cta {{ background:linear-gradient(135deg,var(--tint),#fff); border-color:var(--brand); }}
  .cta p {{ font-size:14px; margin:0 0 14px; }}
  .offer {{ margin:0; padding:0; list-style:none; display:grid; grid-template-columns:1fr 1fr; gap:10px 22px; }}
  .offer li {{ position:relative; padding-left:26px; font-size:14px; font-weight:500; }}
  .offer li::before {{ content:"✓"; position:absolute; left:0; top:0; width:18px; height:18px;
                       background:var(--brand); color:#fff; border-radius:50%; font-size:11px;
                       font-weight:800; text-align:center; line-height:18px; }}

  footer {{ margin-top:30px; padding-top:18px; border-top:1px solid var(--line);
            font-size:11.5px; color:var(--muted); text-align:center; }}
  footer .scoring {{ margin-top:6px; }}

  /* Render gap / SPA */
  .gap-warn {{ border-color:#f59e0b; background:#fffbeb; }}
  .gap-warn h2 {{ color:#b45309; }}
  .gap-warn p {{ font-size:14px; margin:0; }}
  .gap-lead {{ font-size:13.5px; margin:0 0 14px; }}
  .gap-fix {{ font-size:13px; color:var(--muted); margin:12px 0 0; }}
  .gap-scores {{ display:flex; align-items:center; justify-content:center; gap:18px; margin:4px 0 16px; }}
  .gap-score {{ background:var(--tint); border:1px solid var(--line); border-radius:12px; padding:10px 18px; text-align:center; min-width:150px; }}
  .gap-score span {{ display:block; font-size:11px; color:var(--muted); margin-bottom:3px; }}
  .gap-score b {{ font-size:24px; font-weight:800; }} .gap-score i {{ font-style:normal; font-size:14px; }}
  .gap-arrow {{ font-size:18px; font-weight:800; color:var(--brand); }}
  .deltas {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  .deltas th, .deltas td {{ padding:7px 8px; border-top:1px solid var(--line); text-align:left; }}
  .deltas th {{ color:var(--muted); font-size:10.5px; text-transform:uppercase; letter-spacing:.08em; }}
  .deltas td:nth-child(2), .deltas td:nth-child(3), .deltas th:nth-child(2), .deltas th:nth-child(3) {{ text-align:right; color:var(--muted); }}
  .deltas .dl {{ text-align:right; font-weight:700; }}

  @media print {{
    body {{ background:#fff; }}
    .wrap {{ max-width:100%; padding:0; }}
    .card, .cover, .summary {{ break-inside:avoid; }}
    .cover {{ box-shadow:none; }}
  }}
</style>
</head>
<body>
  <div class="wrap">
    <header class="top">
      {logo_html}
      <div class="top-label">GEO / AIO<br>Hazırlık Raporu</div>
    </header>
    {body}
    <footer>
      Bu rapor <b>{_esc(brand)}</b> GEO/AIO Audit aracı ile üretilmiştir · {_esc(when)}
      <div class="scoring">Skorlama ağırlıkları: AI Bot Erişimi 25 · llms.txt 10 · Schema 25 · İçerik 20 · Meta 10 · Hız/Taranabilirlik 10</div>
    </footer>
  </div>
</body>
</html>"""


def export_html(
    report: AuditReport,
    path: str,
    brand: str = "Growity",
    client: str = "",
    logo: str = "",
    client_logo: str = "",
) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(render_html(report, brand=brand, client=client, logo=logo,
                             client_logo=client_logo))
