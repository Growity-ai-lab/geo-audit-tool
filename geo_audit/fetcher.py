"""Pluggable page-fetching strategies.

The audit engine needs the *final* HTML of a page plus a few HTTP-level
signals (status, headers, response time). Historically this was done inline in
``Crawler`` with a ``requests.Session``. Extracting it behind a small
``Fetcher`` protocol lets us swap the network strategy without touching any
analyzer:

* ``RequestsFetcher`` — the original behaviour, a plain ``requests`` GET. Fast,
  cheap, and the default; it returns the raw server HTML (no JavaScript).
* ``PlaywrightFetcher`` — drives a headless Chromium so single-page apps that
  render their content with JavaScript produce the DOM an AI crawler would
  actually see. Heavier (a browser per call), opt-in.

Only the *main page* fetch is pluggable. Sidecar files (robots.txt, llms.txt,
sitemap.xml) are plain text and never need a browser, so ``Crawler`` keeps a
lightweight ``requests`` session for those.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, Protocol

import requests

logger = logging.getLogger("geo_audit.fetcher")

DEFAULT_TIMEOUT = 15
DEFAULT_UA = (
    "Mozilla/5.0 (compatible; GEO-Audit-Tool/0.1; "
    "+https://github.com/growity-ai-lab/geo-audit-tool)"
)


@dataclass
class FetchResponse:
    """Normalised result of fetching a single URL.

    This is deliberately decoupled from ``requests.Response`` so that a
    browser-based fetcher can populate the same shape. Header keys are
    lower-cased for case-insensitive lookups, matching the existing crawler.
    """

    final_url: str
    status_code: int
    ok: bool
    headers: Dict[str, str] = field(default_factory=dict)
    text: str = ""
    content_length: int = 0
    elapsed_ms: float = 0.0
    rendered_with: str = "requests"


class Fetcher(Protocol):
    """Strategy for retrieving the rendered HTML of the target page."""

    def fetch(self, url: str) -> FetchResponse:  # pragma: no cover - protocol
        ...


class RequestsFetcher:
    """Fetch a page with a plain ``requests`` GET (no JavaScript).

    This preserves the exact behaviour the crawler had inline: a single GET
    with redirects followed, the body decoded as text, and response time
    measured around the call.
    """

    rendered_with = "requests"

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        user_agent: str = DEFAULT_UA,
    ):
        self.timeout = timeout
        self.session = session or requests.Session()
        if session is None:
            self.session.headers.update(
                {
                    "User-Agent": user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Encoding": "gzip, deflate, br",
                }
            )

    def fetch(self, url: str) -> FetchResponse:
        start = time.perf_counter()
        resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return FetchResponse(
            final_url=resp.url,
            status_code=resp.status_code,
            ok=resp.ok,
            headers={k.lower(): v for k, v in resp.headers.items()},
            text=resp.text or "",
            content_length=len(resp.content or b""),
            elapsed_ms=elapsed_ms,
            rendered_with="requests",
        )


class PlaywrightFetcher:
    """Fetch a page through headless Chromium, returning the post-JS DOM.

    Use this for single-page apps whose meaningful content (schema, headings,
    text) only exists after client-side rendering. Playwright is an optional
    dependency — importing it is deferred to ``fetch`` so the default
    ``requests`` path never pays for it.
    """

    rendered_with = "playwright"

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        user_agent: str = DEFAULT_UA,
        wait_until: str = "networkidle",
    ):
        self.timeout = timeout
        self.user_agent = user_agent
        self.wait_until = wait_until

    def fetch(self, url: str) -> FetchResponse:
        # Imported lazily: Playwright (and its browser binary) is only needed
        # when JS rendering is explicitly requested.
        from playwright.sync_api import sync_playwright

        timeout_ms = self.timeout * 1000
        start = time.perf_counter()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(user_agent=self.user_agent)
                page = context.new_page()
                response = page.goto(
                    url, wait_until=self.wait_until, timeout=timeout_ms
                )
                html = page.content()
                final_url = page.url
                status_code = response.status if response else 0
                headers = (
                    {k.lower(): v for k, v in response.headers.items()}
                    if response
                    else {}
                )
            finally:
                browser.close()
        elapsed_ms = (time.perf_counter() - start) * 1000.0

        return FetchResponse(
            final_url=final_url,
            status_code=status_code,
            ok=200 <= status_code < 400,
            headers=headers,
            text=html or "",
            content_length=len((html or "").encode("utf-8")),
            elapsed_ms=elapsed_ms,
            rendered_with="playwright",
        )


class FallbackFetcher:
    """Try a primary fetcher, fall back to a secondary one on any failure.

    Used for JS rendering: attempt headless Chromium first, but if the browser
    is unavailable or the render fails/times out, fall back to a plain requests
    GET so the audit still produces a result (degraded, not crashed). The
    returned ``FetchResponse.rendered_with`` reflects which path actually ran.
    """

    def __init__(self, primary: "Fetcher", fallback: "Fetcher"):
        self.primary = primary
        self.fallback = fallback

    def fetch(self, url: str) -> FetchResponse:
        try:
            return self.primary.fetch(url)
        except Exception as exc:  # noqa: BLE001 - any primary failure degrades
            logger.warning(
                "Primary fetch failed (%s); falling back to %s",
                exc,
                type(self.fallback).__name__,
            )
            return self.fallback.fetch(url)
