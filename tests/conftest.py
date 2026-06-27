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
from sqlalchemy.pool import StaticPool

from api import service
from api.config import settings
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
def _deterministic_audits(tmp_path, monkeypatch):
    """Make audits deterministic: temp artifacts, fake fetch, stubbed PDF."""
    monkeypatch.setattr(settings, "artifacts_dir", str(tmp_path))

    def _fake_build_crawler(render_js: bool) -> Crawler:
        crawler = Crawler(fetcher=_FakeFetcher())
        crawler._fetch_text = lambda url: None  # no sidecar network
        return crawler

    monkeypatch.setattr(service, "_build_crawler", _fake_build_crawler)
    monkeypatch.setattr(service.pdf_mod, "html_to_pdf", lambda html: b"%PDF-1.4 fake")


@pytest.fixture
def db_session():
    """Fresh in-memory SQLite shared across the test's requests."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

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
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def client(db_session):
    return TestClient(app)
