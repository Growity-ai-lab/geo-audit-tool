"""Celery tasks: run an enqueued audit and persist its result.

The task owns its own DB session (it may run in a separate worker process). It
loads the queued audit row, runs the engine, and writes the scored result back,
moving status queued → running → done (or → error).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from geo_audit.aggregate import aggregate_reports
from geo_audit.ai_engines import build_engines, build_extractor
from geo_audit.ai_visibility import analyze_visibility, build_prompts
from geo_audit.reporter import render_list_html, render_visibility_html
from geo_audit.scorer import AuditReport

from . import db, models, repository, service
from .celery_app import celery_app
from .config import settings
from .schemas import AuditRequest

logger = logging.getLogger("geo_audit.api.tasks")


@celery_app.task(name="api.tasks.run_audit")
def run_audit_task(
    audit_id: str,
    url: str,
    client_name: str | None,
    brand: str | None,
    render_js: bool,
    compare_render: bool = False,
    page_type: str = "generic",
    target_keyword: str = "",
) -> str:
    """Process a queued audit. Returns the terminal status ("done"/"error")."""
    # Use db.SessionLocal() (attribute access) so tests can rebind it.
    session = db.SessionLocal()
    try:
        audit = session.get(models.Audit, audit_id)
        if audit is None:
            logger.warning("run_audit_task: audit %s not found", audit_id)
            return "error"

        audit.status = "running"
        session.commit()

        try:
            req = AuditRequest(
                url=url,
                client=client_name or "",
                brand=brand,
                render_js=render_js,
                compare_render=compare_render,
                page_type=page_type,
                target_keyword=target_keyword,
            )
            response = service.run_audit(
                req, audit_id=audit_id, client_name=client_name
            )
            # Preserve the linkage captured at enqueue time.
            response.client_id = audit.client_id
            response.user_id = audit.user_id
            repository.apply_result(session, audit, response)
            return audit.status
        except Exception as exc:  # noqa: BLE001 - record failure, don't crash worker
            logger.exception("run_audit_task failed for %s", audit_id)
            session.rollback()
            audit = session.get(models.Audit, audit_id)
            if audit is not None:
                audit.status = "error"
                audit.error = str(exc)
                audit.completed_at = datetime.now(timezone.utc)
                session.commit()
            return "error"
    finally:
        session.close()


@celery_app.task(name="api.tasks.run_batch")
def run_batch_task(
    parent_id: str,
    urls: list[str],
    client_name: str | None,
    brand: str | None,
    render_js: bool,
) -> str:
    """Process a queued URL-list audit: run each URL as a child page audit,
    then aggregate them into the parent and render the combined report.

    Pages run sequentially in this single task (a handful of URLs, and it
    keeps us polite to a single target). Each page is a normal, individually
    downloadable audit; the parent holds the average + strategy report."""
    session = db.SessionLocal()
    try:
        parent = session.get(models.Audit, parent_id)
        if parent is None:
            logger.warning("run_batch_task: parent %s not found", parent_id)
            return "error"

        parent.status = "running"
        session.commit()

        reports: list[AuditReport] = []
        for url in urls:
            child_id = uuid.uuid4().hex
            child = models.Audit(
                id=child_id,
                parent_audit_id=parent_id,
                client_id=parent.client_id,
                user_id=parent.user_id,
                url=url,
                scope="page",
                status="queued",
                render_js=render_js,
            )
            session.add(child)
            session.commit()
            try:
                req = AuditRequest(
                    url=url, client=client_name or "", brand=brand, render_js=render_js
                )
                response = service.run_audit(
                    req, audit_id=child_id, client_name=client_name
                )
                response.client_id = parent.client_id
                response.user_id = parent.user_id
                repository.apply_result(session, child, response)
                reports.append(AuditReport.from_dict(child.report_json))
            except Exception:  # noqa: BLE001 - one bad URL shouldn't sink the batch
                logger.exception("batch page failed: %s (parent %s)", url, parent_id)
                session.rollback()
                child = session.get(models.Audit, child_id)
                if child is not None:
                    child.status = "error"
                    child.error = "audit failed"
                    child.reachable = False
                    child.completed_at = datetime.now(timezone.utc)
                    session.commit()
                reports.append(
                    AuditReport(
                        url=url, final_url=url, reachable=False, error="audit failed",
                        total_score=0.0, max_score=100.0, grade="F", categories=[],
                    )
                )

        aggregate = aggregate_reports(reports)
        brand_name = brand or settings.default_brand
        parent.report_json = aggregate.to_dict()
        parent.report_html = render_list_html(
            aggregate, brand=brand_name, client=client_name or ""
        )
        parent.geo_score = round(aggregate.avg_score, 1)
        parent.grade = aggregate.grade
        parent.reachable = aggregate.reachable_count > 0
        parent.html_url = f"/audits/{parent_id}/report.html"
        parent.pdf_url = f"/audits/{parent_id}/report.pdf"
        parent.status = "done"
        parent.completed_at = datetime.now(timezone.utc)
        session.commit()
        return "done"
    except Exception as exc:  # noqa: BLE001 - record failure, don't crash worker
        logger.exception("run_batch_task failed for %s", parent_id)
        session.rollback()
        parent = session.get(models.Audit, parent_id)
        if parent is not None:
            parent.status = "error"
            parent.error = str(exc)
            parent.completed_at = datetime.now(timezone.utc)
            session.commit()
        return "error"
    finally:
        session.close()


@celery_app.task(name="api.tasks.run_visibility")
def run_visibility_task(
    audit_id: str,
    brand: str,
    domain: str,
    topic: str,
    aliases: list[str],
    manual_prompts: list[str],
    client_name: str | None,
) -> str:
    """Run an AI Visibility analysis: build prompts, query the configured LLM
    engines, aggregate mention/citation results, and render the report.

    Engines are config-gated (only those with an API key run); if none are
    configured the run errors cleanly. A budget cap bounds total API calls."""
    session = db.SessionLocal()
    try:
        audit = session.get(models.Audit, audit_id)
        if audit is None:
            logger.warning("run_visibility_task: audit %s not found", audit_id)
            return "error"
        audit.status = "running"
        session.commit()

        try:
            engines = build_engines(
                openai_key=settings.openai_api_key,
                perplexity_key=settings.perplexity_api_key,
                gemini_key=settings.gemini_api_key,
                claude_key=settings.anthropic_api_key,
                openai_model=settings.openai_model,
                perplexity_model=settings.perplexity_model,
                gemini_model=settings.gemini_model,
                claude_model=settings.ai_commentary_model,
                enable_claude=settings.enable_claude_visibility,
            )
            if not engines:
                raise RuntimeError(
                    "Hiçbir AI motoru yapılandırılmadı — OPENAI/PERPLEXITY/GEMINI "
                    "API anahtarlarından en az birini ayarlayın."
                )
            extractor = build_extractor(
                openai_key=settings.openai_api_key,
                anthropic_key=settings.anthropic_api_key,
                gemini_key=settings.gemini_api_key,
                gemini_model=settings.gemini_model,
            )
            prompts = build_prompts(
                brand, topic=topic, manual_prompts=manual_prompts,
                max_prompts=settings.visibility_max_prompts,
            )
            report = analyze_visibility(
                brand=brand,
                domain=domain,
                prompts=prompts,
                engines=engines,
                extractor=extractor,
                sample_count=settings.visibility_sample_count,
                max_api_calls=settings.visibility_max_api_calls,
                aliases=tuple(aliases or ()),
            )
            brand_name = settings.default_brand
            audit.report_json = report.to_dict()
            audit.report_html = render_visibility_html(
                report, brand=brand_name
            )
            audit.geo_score = round(report.score, 1)
            audit.grade = report.grade
            audit.reachable = True
            audit.html_url = f"/audits/{audit_id}/report.html"
            audit.pdf_url = f"/audits/{audit_id}/report.pdf"
            audit.status = "done"
            audit.completed_at = datetime.now(timezone.utc)
            session.commit()
            return "done"
        except Exception as exc:  # noqa: BLE001
            logger.exception("run_visibility_task failed for %s", audit_id)
            session.rollback()
            audit = session.get(models.Audit, audit_id)
            if audit is not None:
                audit.status = "error"
                audit.error = str(exc)
                audit.completed_at = datetime.now(timezone.utc)
                session.commit()
            return "error"
    finally:
        session.close()
