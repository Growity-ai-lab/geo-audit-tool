"""Celery tasks: run an enqueued audit and persist its result.

The task owns its own DB session (it may run in a separate worker process). It
loads the queued audit row, runs the engine, and writes the scored result back,
moving status queued → running → done (or → error).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from . import db, models, repository, service
from .celery_app import celery_app
from .schemas import AuditRequest

logger = logging.getLogger("geo_audit.api.tasks")


@celery_app.task(name="api.tasks.run_audit")
def run_audit_task(
    audit_id: str,
    url: str,
    client_name: str | None,
    brand: str | None,
    render_js: bool,
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
                url=url, client=client_name or "", brand=brand, render_js=render_js
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
