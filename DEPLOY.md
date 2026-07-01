# Deploy — Render (managed Postgres + Redis + API + worker + frontend)

The repo ships a [`render.yaml`](./render.yaml) Blueprint that provisions the
whole stack. Artifacts (HTML/PDF) are stored in the database and the PDF is
rendered on demand by the API, so the split API/worker services need **no shared
filesystem**.

## 1. Prerequisites
- A [Render](https://render.com) account.
- This repo on GitHub (it is) with the changes on `main`.

## 2. Create the Blueprint
1. Render Dashboard → **New +** → **Blueprint**.
2. Connect the `growity-ai-lab/geo-audit-tool` repo. Render reads `render.yaml`
   and shows: `geo-audit-db`, `geo-audit-redis`, `geo-audit-api`,
   `geo-audit-worker`, `geo-audit-frontend`.
3. It will ask for the values marked `sync: false`:
   - **ADMIN_EMAIL** — first admin login (e.g. `admin@growity.com.tr`)
   - **ADMIN_PASSWORD** — a strong password (this seeds the bootstrap admin)
   - **PAGESPEED_API_KEY** *(optional)* — enables real Core Web Vitals
     (`api` and `worker` — set on both, or leave blank)
   - **ANTHROPIC_API_KEY** *(optional)* — enables AI-generated report
     commentary (executive summary + per-category rationale, Claude Haiku 4.5;
     `api` and `worker` — set on both, or leave blank)
4. Click **Apply**. Render builds the images and starts everything.
   `JWT_SECRET_KEY` is generated automatically.

## 3. First run
- The API runs `alembic upgrade head` on start (creates the schema) and seeds the
  admin from `ADMIN_EMAIL`/`ADMIN_PASSWORD`.
- Open **`https://geo-audit-frontend.onrender.com`** → log in with the admin
  credentials → run an audit.
- API docs: `https://geo-audit-api.onrender.com/docs`.

## 4. If service names get a suffix
Render URLs are `https://<service-name>.onrender.com`. If a name was taken and
Render appended a suffix, update two values to the real URLs and redeploy:
- `geo-audit-api` → env **CORS_ORIGINS** = the frontend's URL
- `geo-audit-frontend` → env **NEXT_PUBLIC_API_BASE_URL** = the API's URL
  (then **Manual Deploy → Clear build cache & deploy**, since it's baked at build)

## Cost / plans
- **Worker** has no free tier (min **Starter**, ~$7/mo) — it must stay running to
  process the queue.
- **DB / Redis / API / frontend** can run on **free** while evaluating, but:
  - free Postgres expires after ~30 days,
  - free web services sleep when idle (cold start on first request).
  For production, move DB + web services to a paid plan (edit `plan:` in
  `render.yaml` or the dashboard).

## Updates
Push to `main` → Render auto-deploys (api/worker/frontend rebuild; migrations run
on api start). To change the frontend's API URL you must clear the build cache
(it's baked at build time).

## Railway (alternative)
The same Docker images work on Railway: create a project, add **PostgreSQL** and
**Redis** plugins, then three services from this repo — `Dockerfile.api`,
`Dockerfile.worker`, and `frontend/Dockerfile`. Set the same env vars
(`DATABASE_URL`, `CELERY_BROKER_URL`/`RESULT_BACKEND` from the plugins,
`JWT_SECRET_KEY`, `ADMIN_EMAIL/PASSWORD`, `CORS_ORIGINS`, and the frontend
`NEXT_PUBLIC_API_BASE_URL` build arg). Railway has no Blueprint equivalent of
`render.yaml`, so services are wired in its dashboard.

## Not yet included
- **Scheduled monitoring (cron)** — periodic re-audits + "score changed" alerts
  are Phase C4 and not built yet. Once added, a Render `cron` service will be
  appended to `render.yaml`.
- **Object storage (R2/S3)** — not needed: reports live in the DB. Revisit if you
  later store many large artifacts.
