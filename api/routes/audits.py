"""Audit endpoints: run, persist, list, fetch detail, and serve artifacts."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import auth, models, repository, storage, tasks
from ..db import get_db
from ..schemas import (
    AuditListResponse,
    AuditRequest,
    AuditResponse,
    AuditSummary,
)

router = APIRouter(tags=["audits"])

# Content types for the two artifact kinds we serve.
_MEDIA_TYPES = {
    "report.html": "text/html; charset=utf-8",
    "report.pdf": "application/pdf",
}


@router.post("/audits", response_model=AuditResponse, status_code=202)
def create_audit(
    req: AuditRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
) -> AuditResponse:
    """Enqueue an audit and return its id + status.

    The heavy work (crawl + PDF) runs in a Celery worker; clients poll
    ``GET /audits/{id}`` until status is ``done`` or ``error``. With the eager
    fallback (no broker) the task runs inline and the response already says
    ``done``.
    """
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=422, detail="url is required")

    # If linked to a stored client, use its name on the report cover.
    client_name: Optional[str] = None
    if req.client_id:
        client = repository.get_client(db, req.client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="client not found")
        client_name = client.name

    audit_id = uuid.uuid4().hex
    repository.create_queued_audit(db, audit_id=audit_id, req=req, user_id=current_user.id)

    tasks.run_audit_task.delay(
        audit_id=audit_id,
        url=req.url,
        client_name=client_name,
        brand=req.brand,
        render_js=req.render_js,
    )

    # Re-read so eager-mode runs (which finish inline) report their final state.
    db.expire_all()
    audit = repository.get_audit(db, audit_id)
    return repository.to_response(audit)


@router.get("/audits", response_model=AuditListResponse)
def list_audits(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    client_id: Optional[str] = Query(None),
) -> AuditListResponse:
    rows, total = repository.list_audits(
        db, limit=limit, offset=offset, client_id=client_id
    )
    items = [
        AuditSummary(
            audit_id=a.id,
            url=a.url,
            final_url=a.final_url,
            client_id=a.client_id,
            user_id=a.user_id,
            reachable=a.reachable,
            geo_score=a.geo_score,
            grade=a.grade,
            status=a.status,
            rendered_with=a.rendered_with,
            created_at=a.created_at,
        )
        for a in rows
    ]
    return AuditListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/audits/{audit_id}", response_model=AuditResponse)
def get_audit(
    audit_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
) -> AuditResponse:
    audit = repository.get_audit(db, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="audit not found")
    return repository.to_response(audit)


@router.get("/audits/{audit_id}/{name}")
def get_artifact(audit_id: str, name: str) -> FileResponse:
    path = storage.artifact_path(audit_id, name)
    if path is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, media_type=_MEDIA_TYPES[name], filename=name)
