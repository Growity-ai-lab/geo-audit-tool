"""Audit orchestration: wraps the pure engine for the web layer.

This mirrors the CLI flow in ``main.py`` (crawl → score → render_html) and adds
PDF rendering plus artifact persistence. No engine logic lives here; it only
composes existing functions so the web and CLI stay behaviourally identical.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from geo_audit.crawler import Crawler
from geo_audit.fetcher import PlaywrightFetcher
from geo_audit.reporter import render_html
from geo_audit.scorer import score

from . import pdf as pdf_mod
from . import storage
from .config import settings
from .schemas import AuditRequest, AuditResponse

logger = logging.getLogger("geo_audit.api")


def _build_crawler(render_js: bool) -> Crawler:
    """Create a Crawler, optionally with the JS-rendering fetcher.

    JS rendering is gated by ``ENABLE_JS_RENDER`` because it needs a Chromium
    install; when requested but unavailable we fall back to the default
    requests fetcher rather than failing the whole audit.
    """
    if render_js and settings.enable_js_render:
        return Crawler(
            timeout=settings.fetch_timeout,
            fetcher=PlaywrightFetcher(timeout=settings.fetch_timeout),
        )
    if render_js and not settings.enable_js_render:
        logger.warning("render_js requested but ENABLE_JS_RENDER is off; using requests")
    return Crawler(timeout=settings.fetch_timeout)


def run_audit(
    req: AuditRequest, audit_id: str | None = None, client_name: str | None = None
) -> AuditResponse:
    """Run a full audit and render HTML + PDF artifacts.

    ``audit_id`` is supplied by the caller (created at enqueue time so it can be
    returned before the work runs); when omitted a fresh one is generated.
    ``client_name`` (e.g. resolved from a stored client) overrides the request's
    ``client`` field for the report cover. Persistence is handled by the caller,
    keeping this function free of DB concerns.
    """
    audit_id = audit_id or uuid.uuid4().hex
    brand = req.brand or settings.default_brand
    cover_client = client_name if client_name is not None else req.client
    started = datetime.now(timezone.utc)

    crawler = _build_crawler(req.render_js)
    crawl_result = crawler.crawl(req.url)
    report = score(crawl_result)

    html = render_html(report, brand=brand, client=cover_client)
    storage.save_html(audit_id, html)
    html_url = f"/audits/{audit_id}/report.html"

    # PDF is best-effort: if Chromium is unavailable the audit still succeeds
    # with JSON + HTML, and the client simply doesn't get a pdf_url.
    pdf_url = None
    try:
        pdf_bytes = pdf_mod.html_to_pdf(html)
        storage.save_pdf(audit_id, pdf_bytes)
        pdf_url = f"/audits/{audit_id}/report.pdf"
    except Exception as exc:  # noqa: BLE001 - browser may be missing/broken
        logger.warning("PDF render failed for %s: %s", audit_id, exc)

    data = report.to_dict()
    return AuditResponse(
        audit_id=audit_id,
        url=data["url"],
        final_url=data["final_url"],
        reachable=data["reachable"],
        error=data["error"],
        geo_score=data["geo_score"],
        max_score=data["max_score"],
        grade=data["grade"],
        rendered_with=crawl_result.rendered_with,
        categories=data["categories"],
        html_url=html_url,
        pdf_url=pdf_url,
        client_id=req.client_id,
        scope="page",
        status="done" if data["reachable"] else "error",
        created_at=started,
        completed_at=datetime.now(timezone.utc),
    )
