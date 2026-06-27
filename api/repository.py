"""Data-access helpers for clients and audits.

Thin functions over the ORM so routes stay declarative and the persistence
shape lives in one place.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from . import models
from .schemas import AuditResponse, ClientCreate, ClientUpdate


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


def save_audit(
    db: Session, response: AuditResponse, *, render_js: bool
) -> models.Audit:
    """Persist a completed audit plus its flattened findings."""
    audit = models.Audit(
        id=response.audit_id,
        client_id=response.client_id,
        user_id=response.user_id,
        url=response.url,
        final_url=response.final_url,
        scope=response.scope,
        status=response.status,
        render_js=render_js,
        rendered_with=response.rendered_with,
        reachable=response.reachable,
        geo_score=response.geo_score,
        grade=response.grade,
        error=response.error,
        report_json=response.model_dump(mode="json"),
        html_url=response.html_url,
        pdf_url=response.pdf_url,
        created_at=response.created_at,
        completed_at=response.completed_at,
    )

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

    db.add(audit)
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
