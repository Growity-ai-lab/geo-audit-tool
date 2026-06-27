"""Pydantic request/response models for the API."""

from typing import List, Optional

from pydantic import BaseModel, Field


class AuditRequest(BaseModel):
    """Payload for ``POST /audits``."""

    url: str = Field(..., description="URL to audit (scheme optional; https assumed).")
    client: str = Field("", description="Client name shown on the report cover.")
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
    """Result of a synchronous audit run."""

    audit_id: str
    url: str
    final_url: str
    reachable: bool
    error: Optional[str] = None
    geo_score: float
    max_score: float
    grade: str
    rendered_with: str
    categories: List[CategorySummary] = []
    # Relative artifact paths (frontend prefixes with the API base URL).
    html_url: Optional[str] = None
    pdf_url: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
