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
from geo_audit.fetcher import FallbackFetcher, PlaywrightFetcher, RequestsFetcher
from geo_audit.reporter import render_html
from geo_audit.scorer import build_render_comparison, looks_like_spa, score

from .config import settings
from .schemas import AuditRequest, AuditResponse

logger = logging.getLogger("geo_audit.api")


def _build_crawler(render_js: bool, with_psi: bool = True) -> Crawler:
    """Create a Crawler with the right fetcher and optional PSI key.

    JS rendering is gated by ``ENABLE_JS_RENDER`` because it needs a Chromium
    install. When enabled, the Playwright fetcher is wrapped in a
    ``FallbackFetcher`` so that if the browser is unavailable or the render
    fails, the audit degrades to a plain requests fetch instead of crashing.
    Real Core Web Vitals are enabled whenever ``PAGESPEED_API_KEY`` is set,
    unless ``with_psi`` is False (compare mode disables it so the raw-vs-rendered
    delta isolates the rendering effect).
    """
    psi_key = (settings.psi_api_key or None) if with_psi else None
    fetcher = None
    if render_js and settings.enable_js_render:
        fetcher = FallbackFetcher(
            PlaywrightFetcher(timeout=settings.fetch_timeout),
            RequestsFetcher(timeout=settings.fetch_timeout),
        )
    elif render_js and not settings.enable_js_render:
        logger.warning("render_js requested but ENABLE_JS_RENDER is off; using requests")

    return Crawler(
        timeout=settings.fetch_timeout,
        fetcher=fetcher,
        psi_api_key=psi_key,
        psi_strategy=settings.psi_strategy,
    )


def _crawl_and_score(req: AuditRequest):
    """Run a single crawl + score, recording the SPA heuristic for raw fetches.

    Returns (crawl_result, report).
    """
    crawler = _build_crawler(req.render_js)
    crawl_result = crawler.crawl(req.url)
    report = score(crawl_result)
    report.spa_suspected = (
        crawl_result.rendered_with == "requests" and looks_like_spa(report)
    )
    return crawl_result, report


def _compare_crawl_and_score(req: AuditRequest):
    """Audit twice — raw (no-JS) vs JS-rendered — and attach the render gap.

    PSI is disabled for both runs so the delta isolates the rendering effect.
    Returns (rendered_crawl_result, rendered_report) as the primary result.
    """
    raw_result = _build_crawler(render_js=False, with_psi=False).crawl(req.url)
    raw_report = score(raw_result)

    rendered_result = _build_crawler(render_js=True, with_psi=False).crawl(req.url)
    rendered_report = score(rendered_result)

    comparison = build_render_comparison(raw_report, rendered_report)
    rendered_report.render_comparison = comparison
    rendered_report.spa_suspected = comparison["spa_suspected"]
    return rendered_result, rendered_report


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

    if req.compare_render and settings.enable_js_render:
        crawl_result, report = _compare_crawl_and_score(req)
    else:
        if req.compare_render:
            logger.warning("compare_render requested but ENABLE_JS_RENDER is off; single run")
        crawl_result, report = _crawl_and_score(req)

    # Render the HTML report and carry it to the persistence layer (stored in
    # the DB). The PDF is produced on demand by the API from this HTML, so no
    # shared filesystem is needed between the worker and the API.
    html = render_html(report, brand=brand, client=cover_client)

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
        spa_suspected=data["spa_suspected"],
        render_comparison=data["render_comparison"],
        html_url=f"/audits/{audit_id}/report.html",
        pdf_url=f"/audits/{audit_id}/report.pdf",
        report_html=html,
        client_id=req.client_id,
        scope="page",
        status="done" if data["reachable"] else "error",
        created_at=started,
        completed_at=datetime.now(timezone.utc),
    )
