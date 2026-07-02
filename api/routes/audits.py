"""Audit endpoints: run, persist, list, fetch detail, and serve artifacts."""

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from geo_audit.overrides import OVERRIDABLE_KEYS
from geo_audit.reporter import render_html

from .. import auth, models, pdf as pdf_mod, repository, tasks
from ..config import settings
from ..db import get_db
from ..schemas import (
    AuditListResponse,
    AuditRequest,
    AuditResponse,
    AuditSummary,
    BatchAuditRequest,
    BatchAuditResponse,
    OverrideUpdate,
)

router = APIRouter(tags=["audits"])

_ARTIFACT_NAMES = ("report.html", "report.pdf")


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
        compare_render=req.compare_render,
    )

    # Re-read so eager-mode runs (which finish inline) report their final state.
    db.expire_all()
    audit = repository.get_audit(db, audit_id)
    return repository.to_response(audit)


# NOTE: the literal "/audits/batch" routes are declared before "/audits/{...}"
# so they aren't shadowed by the parameterized paths below.
@router.post("/audits/batch", response_model=BatchAuditResponse, status_code=202)
def create_batch_audit(
    req: BatchAuditRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
) -> BatchAuditResponse:
    """Enqueue a URL-list audit: each URL becomes its own page audit and the
    parent holds the average score + combined strategy report."""
    urls = [u.strip() for u in req.urls if u and u.strip()]
    if not urls:
        raise HTTPException(status_code=422, detail="at least one url is required")

    client_name: Optional[str] = None
    if req.client_id:
        client = repository.get_client(db, req.client_id)
        if client is None:
            raise HTTPException(status_code=404, detail="client not found")
        client_name = client.name

    parent_id = uuid.uuid4().hex
    repository.create_batch_parent(db, parent_id=parent_id, req=req, user_id=current_user.id)

    tasks.run_batch_task.delay(
        parent_id=parent_id,
        urls=urls,
        client_name=client_name,
        brand=req.brand,
        render_js=req.render_js,
    )

    db.expire_all()
    parent = repository.get_batch(db, parent_id)
    return repository.to_batch_response(parent)


@router.get("/audits/batch/{audit_id}", response_model=BatchAuditResponse)
def get_batch_audit(
    audit_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
) -> BatchAuditResponse:
    parent = repository.get_batch(db, audit_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="list audit not found")
    return repository.to_batch_response(parent)


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
            scope=a.scope,
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


@router.patch("/audits/{audit_id}/overrides", response_model=AuditResponse)
def update_overrides(
    audit_id: str,
    body: OverrideUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
) -> AuditResponse:
    """Confirm (or retract) a manual correction for an ambiguous finding.

    Only findings the crawler flagged with an ``override_key`` (WAF/rate-
    limit blocked automated verification) are affected — see
    ``geo_audit/overrides.py``. Unknown keys are rejected so a frontend typo
    doesn't silently no-op.
    """
    unknown = set(body.overrides) - set(OVERRIDABLE_KEYS)
    if unknown:
        raise HTTPException(
            status_code=422, detail=f"unknown override key(s): {sorted(unknown)}"
        )

    audit = repository.get_audit(db, audit_id)
    if audit is None:
        raise HTTPException(status_code=404, detail="audit not found")
    if not audit.report_json:
        raise HTTPException(
            status_code=409, detail="audit has no report yet (still queued/running)"
        )

    audit = repository.update_overrides(db, audit, body.overrides)
    return repository.to_response(audit)


def _render_artifact_html(audit: models.Audit, db: Session) -> str:
    """The stored HTML if no overrides are active (fast path), else a fresh
    render reflecting the current overrides — the artifact must match what
    ``GET /audits/{id}`` reports."""
    if not audit.overrides:
        return audit.report_html

    report = repository.adjusted_report(audit)
    client_name = ""
    if audit.client_id:
        client = repository.get_client(db, audit.client_id)
        client_name = client.name if client else ""
    return render_html(report, brand=settings.default_brand, client=client_name)


@router.get("/audits/{audit_id}/{name}")
def get_artifact(
    audit_id: str, name: str, db: Session = Depends(get_db)
) -> Response:
    """Serve the report HTML from the DB, or regenerate the PDF on demand.

    Intentionally unauthenticated — the uuid path acts as a capability so
    browser <a href> downloads work without an Authorization header. The HTML
    lives in the DB (no shared filesystem), and the PDF is produced from it via
    headless Chromium when requested.
    """
    if name not in _ARTIFACT_NAMES:
        raise HTTPException(status_code=404, detail="artifact not found")

    audit = repository.get_audit(db, audit_id)
    if audit is None or not audit.report_html:
        raise HTTPException(status_code=404, detail="artifact not found")

    html = _render_artifact_html(audit, db)

    if name == "report.html":
        return Response(content=html, media_type="text/html; charset=utf-8")

    try:
        pdf_bytes = pdf_mod.html_to_pdf(html)
    except Exception as exc:  # noqa: BLE001 - browser may be unavailable
        raise HTTPException(
            status_code=503, detail=f"PDF generation unavailable: {exc}"
        )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="report.pdf"'},
    )
