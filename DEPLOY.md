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
   - **CORS_ORIGINS** (`api`) / **NEXT_PUBLIC_API_BASE_URL** (`frontend`) —
     leave these **blank** for now; the real URLs aren't known until step 3.
4. Click **Apply**. Render builds the images and starts everything.
   `JWT_SECRET_KEY` is generated automatically.

## 3. First run
- The API runs `alembic upgrade head` on start (creates the schema) and seeds the
  admin from `ADMIN_EMAIL`/`ADMIN_PASSWORD`.
- Once all 5 services are live, note the **actual** URLs Render assigned —
  `https://<service-name>.onrender.com`, but if a name was already taken,
  Render silently appends a suffix (e.g. `geo-audit-api-msgt.onrender.com`).
  Check each service's page in the dashboard for its real URL; don't assume
  the un-suffixed name.
- Set the two cross-references to those real URLs (dashboard → service →
  **Environment**):
  - `geo-audit-api` → env **CORS_ORIGINS** = the frontend's real URL
  - `geo-audit-frontend` → env **NEXT_PUBLIC_API_BASE_URL** = the API's real URL
    (then **Manual Deploy → Clear build cache & deploy** on the frontend —
    it's a Next.js build-time value, a normal redeploy won't pick it up)
- Open the frontend's real URL → log in with the admin credentials → run an audit.
- API docs: `<the API's real URL>/docs`.

Both variables are `sync: false` in `render.yaml`, so once set here they
**persist across future deploys** — a `git push` to `main` will rebuild the
images but will not reset these back to a placeholder.

## 4. If service names get a suffix later
Same fix as above: update **CORS_ORIGINS** / **NEXT_PUBLIC_API_BASE_URL** in
the dashboard to the real URLs (frontend needs a build-cache-cleared redeploy
afterward). Because both are `sync: false`, this only needs to be done once.

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
