"""Runtime configuration for the API, sourced from environment variables.

A1 is intentionally dependency-light: no database, no object storage. Audit
artifacts (HTML + PDF) are written to a local directory and served back over
HTTP. Later phases (A2 Postgres, A4 R2) replace this storage layer.
"""

import os
from dataclasses import dataclass, field
from typing import List


def _split_csv(value: str) -> List[str]:
    # Trailing slashes stripped: a browser's Origin header never has one, but
    # a hand-typed dashboard value (e.g. copied from an address bar) often
    # does — an exact-match CORS check would otherwise silently reject it.
    return [
        item.strip().rstrip("/") for item in value.split(",") if item.strip()
    ]


@dataclass
class Settings:
    # Database. Defaults to a local SQLite file for zero-config dev; Docker
    # Compose and production set a Postgres URL via DATABASE_URL.
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL", "sqlite:///./data/geo_audit.db"
        )
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
    # PageSpeed Insights (A5). When a key is set, audits fetch real Core Web
    # Vitals (LCP/CLS/INP + Lighthouse perf). Empty => crawlability-only scoring.
    psi_api_key: str = field(
        default_factory=lambda: os.environ.get("PAGESPEED_API_KEY", "")
    )
    psi_strategy: str = field(
        default_factory=lambda: os.environ.get("PSI_STRATEGY", "mobile")
    )
    # AI-generated report commentary (Claude). When a key is set, every audit
    # gets an executive-summary paragraph + per-category rationale. Empty =>
    # reports render without commentary (no request made).
    anthropic_api_key: str = field(
        default_factory=lambda: os.environ.get("ANTHROPIC_API_KEY", "")
    )
    ai_commentary_model: str = field(
        default_factory=lambda: os.environ.get(
            "AI_COMMENTARY_MODEL", "claude-haiku-4-5"
        )
    )

    # --- AI Visibility (#5): off-site "does the brand show up in LLM answers"
    # Config-gated per engine — an engine runs only if its key is set. Claude
    # is additionally opt-in (ENABLE_CLAUDE_VISIBILITY). Sampling/prompt/budget
    # caps bound the (paid) cost per run.
    openai_api_key: str = field(
        default_factory=lambda: os.environ.get("OPENAI_API_KEY", "")
    )
    perplexity_api_key: str = field(
        default_factory=lambda: os.environ.get("PERPLEXITY_API_KEY", "")
    )
    gemini_api_key: str = field(
        default_factory=lambda: os.environ.get("GEMINI_API_KEY", "")
    )
    openai_model: str = field(
        default_factory=lambda: os.environ.get("OPENAI_MODEL", "gpt-4o")
    )
    perplexity_model: str = field(
        default_factory=lambda: os.environ.get("PERPLEXITY_MODEL", "sonar")
    )
    # A rolling alias so the default tracks the current Flash model (specific
    # dated IDs get retired for new keys). Override with GEMINI_MODEL if your
    # key needs a specific model (e.g. gemini-2.0-flash).
    gemini_model: str = field(
        default_factory=lambda: os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
    )
    enable_claude_visibility: bool = field(
        default_factory=lambda: os.environ.get(
            "ENABLE_CLAUDE_VISIBILITY", "false"
        ).lower()
        in ("1", "true", "yes")
    )
    visibility_sample_count: int = field(
        default_factory=lambda: int(os.environ.get("VISIBILITY_SAMPLE_COUNT", "2"))
    )
    visibility_max_prompts: int = field(
        default_factory=lambda: int(os.environ.get("VISIBILITY_MAX_PROMPTS", "10"))
    )
    # Hard cap on total external API calls per run (cost kill-switch).
    visibility_max_api_calls: int = field(
        default_factory=lambda: int(os.environ.get("VISIBILITY_MAX_API_CALLS", "120"))
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

    # --- Celery / queue (A4) ---------------------------------------------- #
    celery_broker_url: str = field(
        default_factory=lambda: os.environ.get(
            "CELERY_BROKER_URL", "redis://localhost:6379/0"
        )
    )
    celery_result_backend: str = field(
        default_factory=lambda: os.environ.get(
            "CELERY_RESULT_BACKEND", "redis://localhost:6379/0"
        )
    )
    # When true, audit tasks run inline in the calling process (no broker
    # needed). Default true so the app works out-of-the-box; Compose/prod set
    # this false and run a dedicated Celery worker.
    celery_eager: bool = field(
        default_factory=lambda: os.environ.get(
            "CELERY_TASK_ALWAYS_EAGER", "true"
        ).lower()
        in ("1", "true", "yes")
    )


settings = Settings()
