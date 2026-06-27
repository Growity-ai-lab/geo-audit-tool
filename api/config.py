"""Runtime configuration for the API, sourced from environment variables.

A1 is intentionally dependency-light: no database, no object storage. Audit
artifacts (HTML + PDF) are written to a local directory and served back over
HTTP. Later phases (A2 Postgres, A4 R2) replace this storage layer.
"""

import os
from dataclasses import dataclass, field
from typing import List


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass
class Settings:
    # Database. Defaults to a local SQLite file for zero-config dev; Docker
    # Compose and production set a Postgres URL via DATABASE_URL.
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "sqlite:///./data/geo_audit.db"
        )
    )
    # Where rendered HTML/PDF artifacts are written and served from.
    artifacts_dir: str = field(
        default_factory=lambda: os.environ.get("ARTIFACTS_DIR", "data/artifacts")
    )
    # Browser origins allowed to call the API (the Next.js frontend).
    cors_origins: List[str] = field(
        default_factory=lambda: _split_csv(
            os.environ.get("CORS_ORIGINS", "http://localhost:3000")
        )
    )
    # Default branding for reports (overridable per request).
    default_brand: str = field(
        default_factory=lambda: os.environ.get("DEFAULT_BRAND", "Growity")
    )
    # HTTP timeout (seconds) for the engine's page fetch.
    fetch_timeout: int = field(
        default_factory=lambda: int(os.environ.get("FETCH_TIMEOUT", "15"))
    )
    # Allow JS-rendering (Playwright) audits. Disabled where Chromium is absent
    # (e.g. the slim API image); the worker image enables it.
    enable_js_render: bool = field(
        default_factory=lambda: os.environ.get("ENABLE_JS_RENDER", "false").lower()
        in ("1", "true", "yes")
    )

    # --- Auth (A3) -------------------------------------------------------- #
    # JWT signing secret. MUST be set in production; a dev fallback is used
    # locally (with a warning) so the app runs out-of-the-box.
    jwt_secret_key: str = field(
        default_factory=lambda: os.environ.get("JWT_SECRET_KEY", "")
    )
    jwt_algorithm: str = field(
        default_factory=lambda: os.environ.get("JWT_ALGORITHM", "HS256")
    )
    access_token_expire_minutes: int = field(
        default_factory=lambda: int(
            os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "720")
        )
    )
    # Optional admin bootstrapped on startup (admin-seeded model: only an admin
    # can then invite further users).
    admin_email: str = field(
        default_factory=lambda: os.environ.get("ADMIN_EMAIL", "")
    )
    admin_password: str = field(
        default_factory=lambda: os.environ.get("ADMIN_PASSWORD", "")
    )


settings = Settings()
