# claude.md — Notes for AI assistants

This file orients AI assistants (Claude Code and others) working on this repo.

## What this is

A Python CLI that audits a URL for **GEO/AIO** (Generative Engine Optimization /
AI Optimization) readiness and emits a **0–100 GEO Score** with categorized
findings and recommendations.

## Architecture

The data flows in one direction:

```
URL → Crawler (network I/O) → CrawlResult
        → scorer.score() runs each analyzer → AuditReport
        → reporter renders to terminal / JSON
```

- **`geo_audit/__init__.py`** — shared dataclasses: `Finding`
  (`severity`, `message`, `recommendation`) and `CategoryResult`
  (`key`, `name`, `score`, `max_score`, `findings`). Severity constants:
  `OK`, `WARN`, `FAIL`.
- **`geo_audit/crawler.py`** — *all network I/O lives here*. Fetches the page
  once (so analyzers reuse the HTML), plus `robots.txt` and `llms.txt`. Also
  contains `analyze_bot_access()` and `analyze_page_speed()` since both score
  data that only the crawler has.
- **`geo_audit/schema_checker.py`** — `analyze(html)` detects JSON-LD (and
  microdata fallback) and scores presence of high-value schema.org types.
- **`geo_audit/content_analyzer.py`** — `analyze(html)` (headings +
  answer-first), `analyze_meta(html)` (title/description/OG), and
  `analyze_llms_txt(found, url)`.
- **`geo_audit/scorer.py`** — orchestrates all analyzers, sums weighted
  scores, assigns a grade. `CATEGORY_ORDER` is the source of truth for which
  categories run and in what order.
- **`geo_audit/reporter.py`** — `print_report()` / `render_terminal()` and
  `to_json()` / `export_json()`.

## Scoring weights (total = 100)

| Category    | Weight | Where defined |
|-------------|:------:|---------------|
| bot_access  | 25     | `crawler.BOT_MAX_SCORE` |
| llms_txt    | 10     | `content_analyzer.LLMS_MAX_SCORE` |
| schema      | 25     | `schema_checker.MAX_SCORE` |
| content     | 20     | `content_analyzer.MAX_SCORE` |
| meta        | 10     | `content_analyzer.META_MAX_SCORE` |
| page_speed  | 10     | `crawler.SPEED_MAX_SCORE` |

If you change a weight, the category `max_score` constants are the single
place to edit — `scorer` sums them dynamically, so totals stay consistent.

## Conventions

- Every category must return a `CategoryResult` whose `score ≤ max_score`.
- Every finding should carry a `recommendation` when severity is `WARN`/`FAIL`.
- Keep all network calls inside `crawler.py`; analyzers operate on already
  fetched data so they stay pure and unit-testable.
- No network in tests — pass HTML strings / fake `CrawlResult`s directly to
  the analyzers.

## Running

```bash
pip install -r requirements.txt
python main.py example.com
python main.py example.com --json report.json
```

## Ideas / TODO

- Add a unit-test suite (analyzers are pure → easy to test with HTML fixtures).
- Optional real page-speed metrics (Core Web Vitals via PageSpeed Insights API).
- Sitemap.xml discovery and validation.
- Batch mode: audit a list of URLs and emit a CSV.
- Detection of `noai` / `noimageai` meta directives.
