"""Server-side PDF rendering.

The HTML report (``geo_audit.reporter.render_html``) already ships with
``@media print`` styles, ``print-color-adjust: exact`` and base64-embedded
logos, so it is fully self-contained. We reuse it verbatim: load the HTML in
headless Chromium and let the browser's print engine produce the PDF — exactly
what "Print to PDF" in the CLI workflow did, now automated.
"""

from __future__ import annotations


def html_to_pdf(html: str) -> bytes:
    """Render a self-contained HTML string to PDF bytes via headless Chromium.

    Imports Playwright lazily so the module can be imported in environments
    without browsers (e.g. unit tests, the slim API image) — only calling this
    function requires Chromium.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            # ``set_content`` loads the markup directly; the report has no
            # external requests, so we wait only for the load event.
            page.set_content(html, wait_until="load")
            page.emulate_media(media="print")
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            browser.close()
    return pdf_bytes
