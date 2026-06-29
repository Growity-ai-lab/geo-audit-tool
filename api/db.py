"""Database engine, session factory, and FastAPI dependency.

SQLAlchemy 2.0 style. The engine is created lazily from ``DATABASE_URL`` and is
never connected at import time, so tests can override the session dependency
with their own (SQLite) engine without a real Postgres being present.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    """Declarative base shared by all ORM models."""


def _normalize_url(url: str) -> str:
    # Managed Postgres providers (e.g. Render) hand out "postgres://" URLs, but
    # SQLAlchemy 2.0 requires the "postgresql://" scheme. Normalize it.
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def _engine_kwargs(url: str) -> dict:
    # SQLite needs check_same_thread disabled for the threadpool-served
    # sync endpoints; Postgres uses sensible pool defaults.
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


_db_url = _normalize_url(settings.database_url)
engine = create_engine(_db_url, **_engine_kwargs(_db_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Iterator[Session]:
    """Yield a DB session, closing it when the request finishes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
