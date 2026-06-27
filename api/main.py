"""FastAPI application entry point.

Wraps the pure GEO audit engine behind an HTTP API. A1 is synchronous: a
``POST /audits`` runs the full audit in-process and returns the score plus
links to the rendered HTML/PDF. Redis/Postgres/Celery arrive in later phases.

Run locally:
    uvicorn api.main:app --reload
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from geo_audit import __version__

from .config import settings
from .routes import audits, clients
from .schemas import HealthResponse

logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="GEO Audit API",
    version=__version__,
    description="Audit a URL for GEO/AIO readiness and download a branded report.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audits.router)
app.include_router(clients.router)


@app.get("/healthz", response_model=HealthResponse, tags=["meta"])
def healthz() -> HealthResponse:
    """Liveness probe. (DB/Redis pings are added when those services arrive.)"""
    return HealthResponse(status="ok", version=__version__)
