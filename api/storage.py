"""Local-disk artifact storage for A1.

Each audit gets a directory ``<artifacts_dir>/<audit_id>/`` holding the
rendered ``report.html`` and ``report.pdf``. These are served back over HTTP by
the FastAPI app. Later phases swap this for object storage (Cloudflare R2)
behind the same save/path interface.
"""

from __future__ import annotations

import os
from typing import Optional

from .config import settings


def _audit_dir(audit_id: str) -> str:
    return os.path.join(settings.artifacts_dir, audit_id)


def save_html(audit_id: str, html: str) -> str:
    """Write the HTML report and return its absolute path."""
    directory = _audit_dir(audit_id)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "report.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(html)
    return path


def save_pdf(audit_id: str, pdf: bytes) -> str:
    """Write the PDF report and return its absolute path."""
    directory = _audit_dir(audit_id)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "report.pdf")
    with open(path, "wb") as fh:
        fh.write(pdf)
    return path


def artifact_path(audit_id: str, name: str) -> Optional[str]:
    """Return the path of a named artifact if it exists, else None.

    ``name`` is validated against a small allow-list to prevent traversal.
    """
    if name not in ("report.html", "report.pdf"):
        return None
    path = os.path.join(_audit_dir(audit_id), name)
    return path if os.path.isfile(path) else None
