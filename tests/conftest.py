"""Shared fixtures for API tests.

Provides an isolated in-memory SQLite database per test (overriding the app's
get_db dependency) and deterministic, network-free audits (a fake fetcher plus a
stubbed PDF renderer), so the suite never touches Postgres, the network, or
Chromium.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from api import auth as auth_mod
from api import db as db_module
from api import models, pdf as pdf_module, service
from api.celery_app import celery_app
from api.db import Base, get_db
from api.main import app
from geo_audit.crawler import Crawler
from geo_audit.fetcher import FetchResponse

PAGE_HTML = (
    "<!DOCTYPE html><html lang='tr'><head>"
    "<title>Örnek Sayfa</title>"
    "<meta name='description' content='Test açıklaması yeterince uzun bir metin.'>"
    "<script type='application/ld+json'>"
    '{"@context":"https://schema.org","@type":"Organization","name":"Marka"}'
    "</script></head><body><h1>Başlık</h1><h2>Alt</h2>"
    "<p>Yeterince uzun bir içerik paragrafı analiz için buraya yazılır.</p>"
    "</body></html>"
)


class _FakeFetcher:
    def fetch(self, url: str) -> FetchResponse:
        return FetchResponse(
            final_url="https://example.com/",
            status_code=200,
            ok=True,
            headers={"content-encoding": "gzip"},
            text=PAGE_HTML,
            content_length=len(PAGE_HTML),
            elapsed_ms=250.0,
            rendered_with="requests",
        )


@pytest.fixture(autouse=True)
def _deterministic_audits(monkeypatch):
    """Make audits deterministic: fake fetch, stubbed PDF, and run Celery tasks
    inline (eager) so the suite never touches the network, Chromium, or Redis."""

    def _fake_build_crawler(render_js: bool, with_psi: bool = True) -> Crawler:
        crawler = Crawler(fetcher=_FakeFetcher())
        crawler._fetch_text = lambda url, context="": None  # no sidecar network
        return crawler

    monkeypatch.setattr(service, "_build_crawler", _fake_build_crawler)
    # The PDF is rendered on demand by the artifact route (api.pdf).
    monkeypatch.setattr(pdf_module, "html_to_pdf", lambda html: b"%PDF-1.4 fake")
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """Fresh file-backed SQLite for the test.

    File-backed (not in-memory) so the request session and the eager Celery
    task's own session — separate connections — see each other's commits.
    SessionLocal/engine are rebound so the task (which uses db.SessionLocal)
    hits this same database.
    """
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield TestSession
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.fixture
def make_user(db_session):
    """Factory that inserts a real user (hashed password) and returns it."""
    TestSession = db_session

    def _make(email: str, password: str, role: str = "member") -> models.User:
        s = TestSession()
        try:
            user = models.User(
                email=email,
                password_hash=auth_mod.hash_password(password),
                role=role,
            )
            s.add(user)
            s.commit()
            s.refresh(user)
            s.expunge(user)
            return user
        finally:
            s.close()

    return _make


@pytest.fixture
def client(db_session, make_user):
    """Authenticated client: every request acts as a fixed member user.

    Overrides get_current_user so existing endpoint tests don't each need to
    log in; the user is real (in the DB) so audit user_id FKs are valid.
    """
    member = make_user("member@test.local", "password123", role="member")
    member_id = member.id
    TestSession = db_session

    def _override_current_user():
        s = TestSession()
        try:
            return s.get(models.User, member_id)
        finally:
            s.close()

    app.dependency_overrides[auth_mod.get_current_user] = _override_current_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(auth_mod.get_current_user, None)


@pytest.fixture
def auth_client(db_session):
    """Unauthenticated client for exercising the real login/JWT flow."""
    return TestClient(app)
