"""Pydantic request/response models for the API."""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class AuditRequest(BaseModel):
    """Payload for ``POST /audits``."""

    url: str = Field(..., description="URL to audit (scheme optional; https assumed).")
    client: str = Field("", description="Client name shown on the report cover.")
    client_id: Optional[str] = Field(
        None,
        description="Link this audit to a stored client; its name is used on the "
        "report cover (overrides the 'client' field).",
    )
    brand: Optional[str] = Field(
        None, description="Brand in the report header (defaults to server brand)."
    )
    render_js: bool = Field(
        False,
        description="Render the page with headless Chromium (for SPAs). "
        "Requires a worker/image with Playwright browsers installed.",
    )


class CategoryFinding(BaseModel):
    severity: str
    message: str
    recommendation: str = ""


class CategorySummary(BaseModel):
    key: str
    name: str
    score: float
    max_score: float
    ratio: float
    findings: List[CategoryFinding] = []


class AuditResponse(BaseModel):
    """A single audit (POST result and GET /audits/{id} detail).

    Score fields are optional because an audit may still be ``queued`` or
    ``running`` (no result yet); they are populated once ``status`` is ``done``.
    """

    audit_id: str
    url: str
    final_url: Optional[str] = None
    reachable: Optional[bool] = None
    error: Optional[str] = None
    geo_score: Optional[float] = None
    max_score: Optional[float] = None
    grade: Optional[str] = None
    rendered_with: Optional[str] = None
    categories: List[CategorySummary] = []
    # Relative artifact paths (frontend prefixes with the API base URL).
    html_url: Optional[str] = None
    pdf_url: Optional[str] = None
    # Persistence metadata.
    client_id: Optional[str] = None
    user_id: Optional[str] = None
    scope: str = "page"
    status: str = "done"
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class AuditSummary(BaseModel):
    """Compact audit row for the list endpoint (no full report payload)."""

    audit_id: str
    url: str
    final_url: Optional[str] = None
    client_id: Optional[str] = None
    user_id: Optional[str] = None
    reachable: bool
    geo_score: Optional[float] = None
    grade: Optional[str] = None
    status: str
    rendered_with: Optional[str] = None
    created_at: Optional[datetime] = None


class AuditListResponse(BaseModel):
    items: List[AuditSummary]
    total: int
    limit: int
    offset: int


# --- Clients -------------------------------------------------------------- #


class ClientCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    domain: Optional[str] = Field(None, max_length=255)
    logo_url: Optional[str] = Field(None, max_length=500)


class ClientUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    domain: Optional[str] = Field(None, max_length=255)
    logo_url: Optional[str] = Field(None, max_length=500)


class ClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    domain: Optional[str] = None
    logo_url: Optional[str] = None
    created_at: datetime


# --- Auth / users --------------------------------------------------------- #


class UserCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=8, max_length=200)
    role: str = Field("member", pattern="^(admin|member)$")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    role: str
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
