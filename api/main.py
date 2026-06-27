"""FastAPI application entry point.

Wraps the pure GEO audit engine behind an HTTP API. A1 is synchronous: a
``POST /audits`` runs the full audit in-process and returns the score plus
links to the rendered HTML/PDF. Redis/Postgres/Celery arrive in later phases.

Run locally:
    uvicorn api.main:app --reload
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from geo_audit import __version__

from .auth import ensure_admin
from .config import settings
from .db import SessionLocal
from .routes import audits, auth, clients
from .schemas import HealthResponse

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Bootstrap the admin from env (idempotent) once the schema exists.
    db = SessionLocal()
    try:
        ensure_admin(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="GEO Audit API",
    version=__version__,
    description="Audit a URL for GEO/AIO readiness and download a branded report.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(audits.router)
app.include_router(clients.router)


@app.get("/healthz", response_model=HealthResponse, tags=["meta"])
def healthz() -> HealthResponse:
    """Liveness probe. (DB/Redis pings are added when those services arrive.)"""
    return HealthResponse(status="ok", version=__version__)
