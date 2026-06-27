# GEO Audit Tool

A command-line tool for auditing a web page's **GEO (Generative Engine
Optimization)** / **AIO (AI Optimization)** readiness. Give it a URL and it
returns a **0–100 GEO Score**, a letter grade, and categorized findings with
concrete recommendations.

GEO is the practice of optimizing content so that AI answer engines
(ChatGPT, Claude, Perplexity, Google AI Overviews, etc.) can **access**,
**understand**, and **cite** it.

> Çıktılar (terminal raporu ve HTML raporu) **Türkçedir**.

## Müşteri sunumu için hızlı başlangıç

Bir müşteri sitesini tarayıp sunum kalitesinde Türkçe HTML rapor üretmek:

```bash
pip install -r requirements.txt
python main.py www.dardanel.com.tr --html dardanel-rapor.html --client "Dardanel"
```

Kendi kurumsal logonuzu rapora gömmek için `--logo` ekleyin (PNG veya SVG;
rapora base64 olarak gömülür, ayrı dosya gerekmez):

```bash
python main.py www.dardanel.com.tr --html dardanel-rapor.html \
    --client "Dardanel" --logo growity-logo.png --client-logo dardanel-logo.png
```

`--logo` ajansınızın (başlık), `--client-logo` ise müşterinin (kapak) logosunu
gömer. Her ikisi de PNG/SVG kabul eder ve rapora base64 olarak gömülür.

`dardanel-rapor.html` dosyasını tarayıcıda açın; **Ctrl/Cmd + P → PDF olarak
kaydet** ile teklif/leave-behind PDF'i alın. Canlı demo için sadece:

```bash
python main.py www.dardanel.com.tr
```

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

# Türkçe HTML rapor (PDF'e basılabilir, markalı)
python main.py example.com --html rapor.html --client "Müşteri Adı"

# Print JSON to stdout (machine-readable, no terminal report)
python main.py example.com --json -

# Disable colors / suppress terminal output
python main.py example.com --no-color
python main.py example.com --quiet --json report.json
```

### Batch mode

Audit many URLs (one per line; blank lines and `#comments` ignored) and export
a summary CSV (one row per URL, with per-category scores):

```bash
python main.py --batch urls.txt --csv summary.csv
python main.py --batch urls.txt --json all_reports.json   # combined JSON array
```

### Exit codes

| Code | Meaning                                  |
|------|------------------------------------------|
| `0`  | Audit completed, score ≥ 50              |
| `1`  | Audit completed, score < 50             |
| `2`  | Page unreachable                         |

## Web uygulaması (API + arayüz)

Aynı denetim motoru bir web uygulaması olarak da sunulur: ekip üyesi tarayıcıda
bir URL girer, GEO Score'u görür ve CLI ile birebir aynı **markalı PDF/HTML
raporu** indirir. Motor yeniden yazılmaz — FastAPI katmanı onu **import edip
sarmalar** (`api/service.py` → `Crawler().crawl → score → render_html → PDF`).

> **Faz A1–A4**: Postgres kalıcılık + JWT auth + **asenkron audit kuyruğu**
> (Redis + Celery worker). `POST /audits` işi kuyruğa atar ve hemen döner;
> istemci `GET /audits/{id}` ile durumu (`queued→running→done`) poll eder.
> Broker yoksa görevler süreç-içi (eager) çalışır — Redis'siz de çalışır.

### Docker ile (önerilen)

```bash
docker compose up --build
# Arayüz:  http://localhost:3000
# API:     http://localhost:8000  (Swagger: /docs, sağlık: /healthz)
```

Compose; Postgres + Redis + API + **Celery worker** + arayüzü ayağa kaldırır ve
API başlarken Alembic migration'larını (`alembic upgrade head`) otomatik uygular.
Audit'ler kuyruğa atılır ve worker tarafından işlenir (asenkron); arayüz bitene
kadar poll eder. `http://localhost:3000` adresinde bir URL girin → GEO Score +
indirilebilir PDF/HTML raporu (audit veritabanına kaydedilir).

### Yerel geliştirme (Docker'sız)

```bash
# API
pip install -r requirements-api.txt
python -m playwright install chromium      # PDF render için (bir kez)
alembic upgrade head                       # şemayı oluştur (varsayılan: yerel SQLite)
export JWT_SECRET_KEY=$(python -c "import secrets;print(secrets.token_hex(32))")
export ADMIN_EMAIL=admin@growity.local ADMIN_PASSWORD=changeme123  # ilk admin
uvicorn api.main:app --reload              # http://localhost:8000

# Arayüz (ayrı terminal)
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Varsayılan olarak audit görevleri **süreç-içi (eager)** çalışır, yani yerelde
Redis/worker gerekmez. Gerçek asenkron kuyruğu denemek için Redis çalıştırın ve:

```bash
export CELERY_TASK_ALWAYS_EAGER=false CELERY_BROKER_URL=redis://localhost:6379/0
celery -A api.celery_app worker --loglevel=info   # ayrı terminal
```

Veritabanı `DATABASE_URL` ile seçilir; ayarlanmazsa sıfır-konfigürasyon için
yerel bir SQLite dosyası (`sqlite:///./data/geo_audit.db`) kullanılır. Postgres
için: `export DATABASE_URL=postgresql://geo:geo@localhost:5432/geo`.

### Kimlik doğrulama (A3)

Veri endpoint'leri **giriş gerektirir** (JWT, Bearer token). Hesap modeli
*admin-tohumlu + admin-davet*: bir bootstrap admin başlangıçta env'den oluşturulur
(`ADMIN_EMAIL` / `ADMIN_PASSWORD`), sonra yeni kullanıcıları **yalnızca admin**
davet eder (`POST /auth/users`). Açık self-register yoktur. Üretimde
`JWT_SECRET_KEY` mutlaka ayarlanmalıdır.

```bash
# Token al (form-encoded OAuth2 password flow)
curl -X POST localhost:8000/auth/login \
  -d "username=admin@growity.local&password=changeme123"
# → {"access_token":"...","token_type":"bearer"}

# Korumalı çağrı
curl -X POST localhost:8000/audits -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" -d '{"url":"dardanel.com.tr"}'
```

### API

| Method | Yol | Auth | Açıklama |
|--------|-----|------|----------|
| `POST` | `/auth/login` | — | `username`(=email)+`password` (form) → access token |
| `GET`  | `/auth/me` | ✓ | Mevcut kullanıcı |
| `POST` `GET` | `/auth/users` | admin | Kullanıcı davet et / listele |
| `POST` | `/audits` | ✓ | Audit'i **kuyruğa atar** (202) → `{audit_id, status}`; `client_id?` ile müşteriye, çalıştıran kullanıcıya bağlar |
| `GET`  | `/audits` | ✓ | Audit listesi (sayfalı: `limit`, `offset`, `client_id`) |
| `GET`  | `/audits/{id}` | ✓ | Tek audit'in durumu/detayı (`queued`→`running`→`done`/`error`) |
| `GET`  | `/audits/{id}/report.{pdf,html}` | — | Üretilen rapor (uuid yol = yetenek; tarayıcı indirmesi için açık) |
| `POST` `GET` `PATCH` `DELETE` | `/clients[/{id}]` | ✓ | Müşteri CRUD'u |
| `GET`  | `/healthz` | — | Sağlık kontrolü |

Tüm giriş yapan kullanıcılar tüm audit/müşterileri görür (paylaşımlı erişim).
`render_js=true` SPA siteleri için Playwright ile render eder
(`ENABLE_JS_RENDER=true` gerekir). Müşteri silinince audit geçmişi korunur
(`client_id` NULL'a çekilir).

## Scoring model

The GEO Score is a weighted sum of six categories (100 points total):

| # | Category                         | Weight | What it checks |
|---|----------------------------------|:------:|----------------|
| 1 | **AI Bot Access**                | 25     | Whether `GPTBot`, `ClaudeBot`, `PerplexityBot` are allowed in `robots.txt` |
| 2 | **llms.txt**                     | 10     | Presence of a root `/llms.txt` file |
| 3 | **Schema Markup**                | 25     | JSON-LD / schema.org types: `FAQPage`, `Organization`, `HowTo`, `Article` |
| 4 | **Content Structure**            | 20     | Single H1, H2 hierarchy, answer-first lead paragraph |
| 5 | **Meta Signals**                 | 10     | `<title>`, meta description, Open Graph tags |
| 6 | **Page Speed / Crawlability**    | 10     | HTTP 200, response time, HTTPS, compression, sitemap.xml |

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
├── requirements-dev.txt     # + pytest
├── README.md
├── claude.md                # Notes for AI assistants working on this repo
├── geo_audit/               # Pure audit engine (no web deps)
│   ├── __init__.py          # Shared data models (Finding, CategoryResult)
│   ├── crawler.py           # robots.txt, AI-bot access, speed, sitemap
│   ├── fetcher.py           # Pluggable page fetch (RequestsFetcher / PlaywrightFetcher)
│   ├── schema_checker.py    # JSON-LD / schema.org detection
│   ├── content_analyzer.py  # Headings, answer-first, llms.txt, meta signals
│   ├── scorer.py            # Weighted scoring + grading engine
│   ├── reporter.py          # Terminal / HTML / JSON / CSV output
│   └── batch.py             # Multi-URL auditing
├── api/                     # FastAPI layer (wraps the engine; A1–A3)
│   ├── main.py              # App, CORS, /healthz, admin bootstrap (lifespan)
│   ├── auth.py              # Password hashing, JWT, get_current_user/require_admin
│   ├── celery_app.py        # Celery instance (eager fallback if no broker)
│   ├── tasks.py             # run_audit_task: queued → running → done/error
│   ├── routes/auth.py       # Login, /me, admin user invites
│   ├── routes/audits.py     # POST(enqueue)/GET /audits + artifact serving
│   ├── routes/clients.py    # Clients CRUD
│   ├── service.py           # crawl → score → render_html → PDF
│   ├── pdf.py               # Playwright print-to-PDF
│   ├── db.py                # Engine, session, get_db dependency
│   ├── models.py            # SQLAlchemy models (User, Client, Audit, AuditFinding)
│   ├── repository.py        # Data-access helpers
│   ├── schemas.py           # Pydantic request/response models
│   ├── storage.py           # Local-disk artifact store
│   └── config.py            # Env-driven settings
├── alembic/                 # DB migrations (alembic upgrade head)
├── frontend/                # Next.js app (URL form → score + downloads)
├── Dockerfile.api           # API image (Playwright base, for sync PDF)
├── Dockerfile.worker        # Worker image (A4-ready)
├── docker-compose.yml       # api + frontend
└── tests/                   # pytest suite (engine + fetcher + API wiring)
```

## Development & tests

The analyzers are pure functions over already-fetched data, so the test suite
runs entirely offline (no network):

```bash
pip install -r requirements-dev.txt
pytest -q
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
