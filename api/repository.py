"""Data-access helpers for clients and audits.

Thin functions over the ORM so routes stay declarative and the persistence
shape lives in one place.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import models
from .schemas import AuditRequest, AuditResponse, ClientCreate, ClientUpdate


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


def to_response(audit: models.Audit) -> AuditResponse:
    """Build an AuditResponse from a row.

    For a finished audit the stored ``report_json`` is the source of truth; for
    a queued/running one (no report yet) a minimal status view is returned.
    """
    if audit.report_json:
        data = dict(audit.report_json)
        # The row's status is authoritative (report_json was written at done).
        data["status"] = audit.status
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


def list_audits(
    db: Session,
    *,
    limit: int = 20,
    offset: int = 0,
    client_id: Optional[str] = None,
) -> Tuple[List[models.Audit], int]:
    """Return a page of audits (newest first) and the total count."""
    query = select(models.Audit)
    count_query = select(func.count()).select_from(models.Audit)
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
