"""Data-access helpers for clients and audits.

Thin functions over the ORM so routes stay declarative and the persistence
shape lives in one place.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from geo_audit.overrides import apply_overrides
from geo_audit.scorer import AuditReport

from . import models
from .schemas import (
    AuditRequest,
    AuditResponse,
    BatchAuditRequest,
    BatchAuditResponse,
    ClientCreate,
    ClientUpdate,
    PageSummary,
)


# --- Clients -------------------------------------------------------------- #


def create_client(db: Session, data: ClientCreate) -> models.Client:
    client = models.Client(
        name=data.name, domain=data.domain, logo_url=data.logo_url
    )
    db.add(client)
    db.commit()
    db.refresh(client)
    return client


def list_clients(db: Session) -> List[models.Client]:
    return list(
        db.scalars(select(models.Client).order_by(models.Client.created_at.desc()))
    )


def get_client(db: Session, client_id: str) -> Optional[models.Client]:
    return db.get(models.Client, client_id)


def update_client(
    db: Session, client: models.Client, data: ClientUpdate
) -> models.Client:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(client, field, value)
    db.commit()
    db.refresh(client)
    return client


def delete_client(db: Session, client: models.Client) -> None:
    db.delete(client)
    db.commit()


# --- Audits --------------------------------------------------------------- #


def create_queued_audit(
    db: Session, *, audit_id: str, req: AuditRequest, user_id: Optional[str]
) -> models.Audit:
    """Create a placeholder audit row in 'queued' state before processing."""
    audit = models.Audit(
        id=audit_id,
        client_id=req.client_id,
        user_id=user_id,
        url=req.url,
        scope="page",
        status="queued",
        render_js=req.render_js,
    )
    db.add(audit)
    db.commit()
    db.refresh(audit)
    return audit


def create_batch_parent(
    db: Session, *, parent_id: str, req: BatchAuditRequest, user_id: Optional[str]
) -> models.Audit:
    """Create the placeholder 'list' audit that its page audits hang off."""
    parent = models.Audit(
        id=parent_id,
        client_id=req.client_id,
        user_id=user_id,
        url=f"{len(req.urls)} URL",  # human label; children hold real URLs
        scope="list",
        status="queued",
        render_js=req.render_js,
    )
    db.add(parent)
    db.commit()
    db.refresh(parent)
    return parent


def to_batch_response(parent: models.Audit) -> BatchAuditResponse:
    """Build a BatchAuditResponse from a list audit and its page children.

    The aggregate lives in ``parent.report_json`` (written when the batch
    finishes); per-page rows come from the child audits so each links to its
    own report artifacts.
    """
    pages = [
        PageSummary(
            audit_id=c.id,
            url=c.url,
            final_url=c.final_url,
            reachable=bool(c.reachable),
            geo_score=c.geo_score,
            grade=c.grade,
            status=c.status,
            error=c.error,
            html_url=c.html_url,
            pdf_url=c.pdf_url,
        )
        for c in parent.children
    ]
    agg = parent.report_json or {}
    return BatchAuditResponse(
        audit_id=parent.id,
        status=parent.status,
        url_count=agg.get("url_count", len(pages)),
        reachable_count=agg.get("reachable_count", 0),
        avg_score=agg.get("avg_score"),
        grade=agg.get("grade"),
        category_averages=agg.get("category_averages", []),
        top_gaps=agg.get("top_gaps", []),
        pages=pages,
        html_url=parent.html_url,
        pdf_url=parent.pdf_url,
        client_id=parent.client_id,
        user_id=parent.user_id,
        created_at=parent.created_at,
        completed_at=parent.completed_at,
    )


def apply_result(
    db: Session, audit: models.Audit, response: AuditResponse
) -> models.Audit:
    """Write a finished audit's scored result onto its (queued) row."""
    audit.final_url = response.final_url
    audit.status = response.status
    audit.rendered_with = response.rendered_with
    audit.reachable = bool(response.reachable)
    audit.geo_score = response.geo_score
    audit.grade = response.grade
    audit.error = response.error
    audit.report_json = response.model_dump(mode="json")
    audit.report_html = response.report_html
    audit.html_url = response.html_url
    audit.pdf_url = response.pdf_url
    audit.completed_at = response.completed_at

    # Replace any prior findings with the fresh flattened set.
    audit.findings.clear()
    sort_index = 0
    for category in response.categories:
        for finding in category.findings:
            audit.findings.append(
                models.AuditFinding(
                    category_key=category.key,
                    severity=finding.severity,
                    message=finding.message,
                    recommendation=finding.recommendation or None,
                    sort_index=sort_index,
                )
            )
            sort_index += 1

    db.commit()
    db.refresh(audit)
    return audit


def adjusted_report(audit: models.Audit) -> Optional[AuditReport]:
    """Reconstruct the audit's report with any confirmed overrides applied.

    ``audit.report_json`` (the automated baseline) is never mutated — this
    re-applies ``audit.overrides`` fresh on every call, so un-checking an
    override is just removing its key, not needing a stored "original" to
    revert to. Returns None for a queued/running/errored audit (no report yet).
    """
    if not audit.report_json:
        return None
    report = AuditReport.from_dict(dict(audit.report_json))
    return apply_overrides(report, audit.overrides or {})


def to_response(audit: models.Audit) -> AuditResponse:
    """Build an AuditResponse from a row.

    For a finished audit the stored ``report_json`` is the source of truth
    (with overrides applied on top); for a queued/running one (no report yet)
    a minimal status view is returned.
    """
    if audit.report_json:
        data = dict(audit.report_json)
        report = adjusted_report(audit)
        if report is not None:
            data.update(report.to_dict())
        # The row's status is authoritative (report_json was written at done).
        data["status"] = audit.status
        data["overrides"] = audit.overrides or {}
        return AuditResponse.model_validate(data)
    return AuditResponse(
        audit_id=audit.id,
        url=audit.url,
        status=audit.status,
        client_id=audit.client_id,
        user_id=audit.user_id,
        error=audit.error,
        created_at=audit.created_at,
        completed_at=audit.completed_at,
    )


def update_overrides(
    db: Session, audit: models.Audit, new_overrides: Dict[str, bool]
) -> models.Audit:
    """Merge new override values into the audit and refresh its cached score.

    ``geo_score``/``grade`` columns (used by the list endpoint) are kept in
    sync with the overridden result so both views agree.
    """
    audit.overrides = {**(audit.overrides or {}), **new_overrides}
    report = adjusted_report(audit)
    if report is not None:
        audit.geo_score = round(report.total_score, 1)
        audit.grade = report.grade
    db.commit()
    db.refresh(audit)
    return audit


def list_audits(
    db: Session,
    *,
    limit: int = 20,
    offset: int = 0,
    client_id: Optional[str] = None,
) -> Tuple[List[models.Audit], int]:
    """Return a page of audits (newest first) and the total count.

    Page audits that belong to a URL-list (``parent_audit_id`` set) are hidden
    from the top-level history — they appear under their parent list audit —
    so the list stays one row per user-initiated run.
    """
    query = select(models.Audit).where(models.Audit.parent_audit_id.is_(None))
    count_query = (
        select(func.count())
        .select_from(models.Audit)
        .where(models.Audit.parent_audit_id.is_(None))
    )
    if client_id is not None:
        query = query.where(models.Audit.client_id == client_id)
        count_query = count_query.where(models.Audit.client_id == client_id)

    total = db.scalar(count_query) or 0
    rows = list(
        db.scalars(
            query.order_by(models.Audit.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    )
    return rows, total


def get_audit(db: Session, audit_id: str) -> Optional[models.Audit]:
    return db.scalar(
        select(models.Audit)
        .where(models.Audit.id == audit_id)
        .options(selectinload(models.Audit.findings))
    )


def get_batch(db: Session, audit_id: str) -> Optional[models.Audit]:
    """Load a list audit with its page children eagerly (for the response)."""
    return db.scalar(
        select(models.Audit)
        .where(models.Audit.id == audit_id, models.Audit.scope == "list")
        .options(selectinload(models.Audit.children))
    )
