"""Google PageSpeed Insights (PSI) client for real Core Web Vitals.

Fetches LCP / CLS / INP and the Lighthouse performance score for a URL. Lab
metrics (always present) come from ``lighthouseResult``; field/CrUX metrics
(real-user data, present only for sites with enough traffic) come from
``loadingExperience``. INP has no standard lab audit, so it is read from field
data when available.

The single entry point, :func:`fetch_psi`, returns ``None`` on any failure
(network, quota, bad response) so the caller can degrade gracefully to the
crawlability-only page-speed score.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger("geo_audit.pagespeed")

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
DEFAULT_TIMEOUT = 30


@dataclass
class PSIResult:
    """Parsed Core Web Vitals from a PageSpeed Insights run."""

    lcp_ms: Optional[float] = None       # Largest Contentful Paint (ms)
    cls: Optional[float] = None          # Cumulative Layout Shift (unitless)
    inp_ms: Optional[float] = None       # Interaction to Next Paint (ms)
    perf_score: Optional[float] = None   # Lighthouse performance score 0-100
    strategy: str = "mobile"


def _lab_numeric(audits: dict, key: str) -> Optional[float]:
    audit = audits.get(key)
    if isinstance(audit, dict):
        value = audit.get("numericValue")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def _field_inp_ms(loading_experience: dict) -> Optional[float]:
    metrics = (loading_experience or {}).get("metrics", {})
    inp = metrics.get("INTERACTION_TO_NEXT_PAINT")
    if isinstance(inp, dict):
        value = inp.get("percentile")
        if isinstance(value, (int, float)):
            return float(value)
    return None


def parse_psi(payload: dict, strategy: str = "mobile") -> PSIResult:
    """Extract Core Web Vitals from a raw PSI v5 response body."""
    lighthouse = payload.get("lighthouseResult", {}) or {}
    audits = lighthouse.get("audits", {}) or {}

    perf_score: Optional[float] = None
    categories = lighthouse.get("categories", {}) or {}
    perf = categories.get("performance")
    if isinstance(perf, dict) and isinstance(perf.get("score"), (int, float)):
        perf_score = round(float(perf["score"]) * 100, 1)

    return PSIResult(
        lcp_ms=_lab_numeric(audits, "largest-contentful-paint"),
        cls=_lab_numeric(audits, "cumulative-layout-shift"),
        inp_ms=_field_inp_ms(payload.get("loadingExperience", {})),
        perf_score=perf_score,
        strategy=strategy,
    )


def fetch_psi(
    url: str,
    api_key: str,
    strategy: str = "mobile",
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[PSIResult]:
    """Run PageSpeed Insights for ``url``; return parsed CWV or ``None``.

    Never raises — any error (network, non-200, bad JSON) is logged and yields
    ``None`` so the audit continues without field data.
    """
    params = {
        "url": url,
        "strategy": strategy,
        "category": "performance",
    }
    if api_key:
        params["key"] = api_key

    try:
        resp = requests.get(PSI_ENDPOINT, params=params, timeout=timeout)
        if resp.status_code != 200:
            logger.warning("PSI returned HTTP %s for %s", resp.status_code, url)
            return None
        result = parse_psi(resp.json(), strategy=strategy)
    except (requests.RequestException, ValueError) as exc:
        logger.warning("PSI fetch failed for %s: %s", url, exc)
        return None

    # If nothing useful parsed, treat as a miss.
    if result.perf_score is None and result.lcp_ms is None and result.cls is None:
        logger.warning("PSI response for %s had no usable metrics", url)
        return None
    return result
