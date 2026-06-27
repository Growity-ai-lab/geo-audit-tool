"""Audit endpoints: run an audit and serve its artifacts."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .. import service, storage
from ..schemas import AuditRequest, AuditResponse

router = APIRouter(tags=["audits"])

# Content types for the two artifact kinds we serve.
_MEDIA_TYPES = {
    "report.html": "text/html; charset=utf-8",
    "report.pdf": "application/pdf",
}


# Defined as a *sync* endpoint on purpose: the engine (and Playwright's sync
# API for PDF) block, so Starlette runs this in a worker thread, keeping the
# event loop free and avoiding the asyncio/sync-Playwright conflict.
@router.post("/audits", response_model=AuditResponse)
def create_audit(req: AuditRequest) -> AuditResponse:
    if not req.url or not req.url.strip():
        raise HTTPException(status_code=422, detail="url is required")
    return service.run_audit(req)


@router.get("/audits/{audit_id}/{name}")
def get_artifact(audit_id: str, name: str) -> FileResponse:
    path = storage.artifact_path(audit_id, name)
    if path is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(path, media_type=_MEDIA_TYPES[name], filename=name)
