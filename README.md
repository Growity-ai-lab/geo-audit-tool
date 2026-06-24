# GEO Audit Tool

A command-line tool for auditing a web page's **GEO (Generative Engine
Optimization)** / **AIO (AI Optimization)** readiness. Give it a URL and it
returns a **0–100 GEO Score**, a letter grade, and categorized findings with
concrete recommendations.

GEO is the practice of optimizing content so that AI answer engines
(ChatGPT, Claude, Perplexity, Google AI Overviews, etc.) can **access**,
**understand**, and **cite** it.

## Installation

```bash
git clone https://github.com/growity-ai-lab/geo-audit-tool.git
cd geo-audit-tool
pip install -r requirements.txt
```

Requires Python 3.9+.

## Usage

```bash
# Basic audit (pretty terminal report)
python main.py https://example.com

# Scheme is optional — https is assumed
python main.py example.com

# Export JSON to a file
python main.py example.com --json report.json

# Print JSON to stdout (machine-readable, no terminal report)
python main.py example.com --json -

# Disable colors / suppress terminal output
python main.py example.com --no-color
python main.py example.com --quiet --json report.json
```

### Exit codes

| Code | Meaning                                  |
|------|------------------------------------------|
| `0`  | Audit completed, score ≥ 50              |
| `1`  | Audit completed, score < 50             |
| `2`  | Page unreachable                         |

## Scoring model

The GEO Score is a weighted sum of six categories (100 points total):

| # | Category                         | Weight | What it checks |
|---|----------------------------------|:------:|----------------|
| 1 | **AI Bot Access**                | 25     | Whether `GPTBot`, `ClaudeBot`, `PerplexityBot` are allowed in `robots.txt` |
| 2 | **llms.txt**                     | 10     | Presence of a root `/llms.txt` file |
| 3 | **Schema Markup**                | 25     | JSON-LD / schema.org types: `FAQPage`, `Organization`, `HowTo`, `Article` |
| 4 | **Content Structure**            | 20     | Single H1, H2 hierarchy, answer-first lead paragraph |
| 5 | **Meta Signals**                 | 10     | `<title>`, meta description, Open Graph tags |
| 6 | **Page Speed / Crawlability**    | 10     | HTTP 200, response time, HTTPS, compression |

### Grades

| Score   | Grade |
|---------|:-----:|
| 90–100  | A |
| 80–89   | B |
| 70–79   | C |
| 60–69   | D |
| 50–59   | E |
| 0–49    | F |

## Project structure

```
geo-audit-tool/
├── main.py                  # CLI entry point
├── requirements.txt
├── README.md
├── claude.md                # Notes for AI assistants working on this repo
└── geo_audit/
    ├── __init__.py          # Shared data models (Finding, CategoryResult)
    ├── crawler.py           # URL fetch, robots.txt, AI-bot access, page speed
    ├── schema_checker.py    # JSON-LD / schema.org detection
    ├── content_analyzer.py  # Headings, answer-first, llms.txt, meta signals
    ├── scorer.py            # Weighted scoring + grading engine
    └── reporter.py          # Terminal output + JSON export
```

## Example output

```
════════════════════════════════════════════════════════════════
  GEO / AIO AUDIT REPORT
════════════════════════════════════════════════════════════════
  URL: https://example.com

  GEO SCORE: 72/100  ████████████████████░░░░  Grade C

  AI Bot Access                 25.0/25   ████████████
      ✓ GPTBot is allowed to crawl this page.
      ...
```

## License

MIT
