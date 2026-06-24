"""Batch auditing: run the audit over many URLs and collect reports."""

from typing import Callable, List, Optional

from .crawler import Crawler
from .scorer import AuditReport, score


def read_url_list(path: str) -> List[str]:
    """Read URLs from a file, one per line. Blank lines and #comments skipped."""
    urls: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    return urls


def audit_many(
    urls: List[str],
    timeout: int = 15,
    on_progress: Optional[Callable[[int, int, AuditReport], None]] = None,
) -> List[AuditReport]:
    """Audit each URL sequentially and return the list of reports.

    ``on_progress(index, total, report)`` is invoked after each audit, letting
    the caller show progress without this module depending on any output layer.
    """
    crawler = Crawler(timeout=timeout)
    reports: List[AuditReport] = []
    total = len(urls)
    for i, url in enumerate(urls, start=1):
        report = score(crawler.crawl(url))
        reports.append(report)
        if on_progress:
            on_progress(i, total, report)
    return reports
