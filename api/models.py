"""SQLAlchemy ORM models for persisted audits and clients.

Kept intentionally cross-database (no Postgres-only types) so the test suite can
run on SQLite while production uses Postgres. ``report_json`` uses the generic
JSON type, which maps to JSON on Postgres and TEXT-encoded JSON on SQLite.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """A team member who can log in and run audits."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="member", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)


class Client(Base):
    """An agency client whose sites get audited."""

    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    domain: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, nullable=False)

    # No delete cascade: audits are valuable history and outlive their client.
    # Deleting a client nulls the link (FK ON DELETE SET NULL / ORM nullify).
    audits: Mapped[List["Audit"]] = relationship(back_populates="client")


class Audit(Base):
    """A single audit run and its scored result."""

    __tablename__ = "audits"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    client_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Who ran the audit (shared-access model: recorded, not used for isolation).
    user_id: Mapped[Optional[str]] = mapped_column(
        String(32),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    final_url: Mapped[Optional[str]] = mapped_column(String(2048), nullable=True)
    scope: Mapped[str] = mapped_column(String(16), default="page", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="done", nullable=False)
    render_js: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rendered_with: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    reachable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    geo_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    grade: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    ai_visibility_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    site_aggregate_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    report_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    # Rendered HTML report, stored in the DB so any service (api) can serve it
    # and regenerate the PDF on demand — no shared filesystem needed across the
    # split api/worker services in production.
    report_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    html_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    pdf_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, nullable=False, index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    client: Mapped[Optional[Client]] = relationship(back_populates="audits")
    findings: Mapped[List["AuditFinding"]] = relationship(
        back_populates="audit",
        cascade="all, delete-orphan",
        order_by="AuditFinding.sort_index",
    )


class AuditFinding(Base):
    """A flattened copy of a single finding, for dashboard/trend queries.

    The authoritative source for rendering remains ``Audit.report_json``; this
    table exists so findings can be queried without unpacking JSON.
    """

    __tablename__ = "audit_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    audit_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("audits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    recommendation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sort_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    audit: Mapped[Audit] = relationship(back_populates="findings")
