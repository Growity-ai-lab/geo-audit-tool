#!/usr/bin/env python3
"""GEO/AIO Audit Tool — CLI entry point.

Usage:
    python main.py https://example.com
    python main.py example.com --json report.json
    python main.py example.com --json -            # JSON to stdout
    python main.py example.com --no-color
"""

import argparse
import sys

from geo_audit import __version__
from geo_audit.crawler import Crawler
from geo_audit.reporter import export_json, print_report, to_json
from geo_audit.scorer import score


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geo-audit",
        description="Audit a URL for GEO/AIO readiness and produce a 0-100 GEO Score.",
    )
    parser.add_argument("url", help="URL to audit (scheme optional; https assumed).")
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="Export the report as JSON. Use '-' to write JSON to stdout.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="HTTP timeout in seconds (default: 15).",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI colors in terminal output.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the terminal report (useful with --json).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    crawler = Crawler(timeout=args.timeout)
    crawl_result = crawler.crawl(args.url)
    report = score(crawl_result)

    json_to_stdout = args.json == "-"

    if not args.quiet and not json_to_stdout:
        print_report(report, color=False if args.no_color else None)

    if args.json:
        if json_to_stdout:
            print(to_json(report))
        else:
            export_json(report, args.json)
            if not args.quiet:
                print(f"JSON report written to {args.json}")

    # Exit code reflects reachability and a passing-ish score.
    if not report.reachable:
        return 2
    return 0 if report.total_score >= 50 else 1


if __name__ == "__main__":
    sys.exit(main())
