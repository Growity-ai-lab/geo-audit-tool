#!/usr/bin/env python3
"""GEO/AIO Audit Tool — CLI entry point.

Usage:
    python main.py https://example.com
    python main.py example.com --html rapor.html --client "Dardanel"
    python main.py example.com --json report.json
    python main.py example.com --json -            # JSON to stdout
    python main.py example.com --no-color
"""

import argparse
import sys

from geo_audit import __version__
from geo_audit.batch import audit_many, read_url_list
from geo_audit.crawler import Crawler
from geo_audit.reporter import (
    export_csv,
    export_html,
    export_json,
    print_report,
    to_json,
)
from geo_audit.scorer import score


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="geo-audit",
        description="Audit a URL for GEO/AIO readiness and produce a 0-100 GEO Score.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="URL to audit (scheme optional; https assumed).",
    )
    parser.add_argument(
        "--batch",
        metavar="FILE",
        help="Audit many URLs listed one-per-line in FILE (use with --csv).",
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help="Export a summary CSV (one row per URL). Most useful with --batch.",
    )
    parser.add_argument(
        "--json",
        metavar="PATH",
        help="Export the report as JSON. Use '-' to write JSON to stdout.",
    )
    parser.add_argument(
        "--html",
        metavar="PATH",
        help="Export a client-facing Turkish HTML report (printable to PDF).",
    )
    parser.add_argument(
        "--brand",
        default="Growity",
        help="Brand name shown in the HTML report header (default: Growity).",
    )
    parser.add_argument(
        "--client",
        default="",
        help="Client name shown in the HTML report header (e.g. Dardanel).",
    )
    parser.add_argument(
        "--logo",
        default="",
        metavar="PATH",
        help="Path to a logo image (PNG/SVG) embedded in the HTML report header. "
        "If omitted, the built-in Growity wordmark is used.",
    )
    parser.add_argument(
        "--client-logo",
        default="",
        metavar="PATH",
        help="Path to the client's logo (PNG/SVG), shown on the report cover.",
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


def _run_batch(args) -> int:
    urls = read_url_list(args.batch)
    if not urls:
        print(f"{args.batch} içinde URL bulunamadı.", file=sys.stderr)
        return 2

    def on_progress(i, total, report):
        if not args.quiet:
            status = (
                f"{report.total_score:.0f}/100 ({report.grade})"
                if report.reachable
                else "erişilemedi"
            )
            print(f"[{i}/{total}] {report.url} → {status}")

    reports = audit_many(urls, timeout=args.timeout, on_progress=on_progress)

    if args.csv:
        export_csv(reports, args.csv)
        if not args.quiet:
            print(f"CSV özeti yazıldı: {args.csv}")
    if args.json and args.json != "-":
        # Write a combined JSON array for batch runs.
        import json as _json

        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(
                _json.dumps(
                    [r.to_dict() for r in reports], indent=2, ensure_ascii=False
                )
            )
        if not args.quiet:
            print(f"JSON raporu yazıldı: {args.json}")
    if args.html:
        # One HTML file per URL: <stem>-<n><suffix>.
        import os

        stem, ext = os.path.splitext(args.html)
        ext = ext or ".html"
        for n, report in enumerate(reports, start=1):
            path = f"{stem}-{n}{ext}"
            export_html(report, path, brand=args.brand, client=args.client,
                        logo=args.logo, client_logo=args.client_logo)
        if not args.quiet:
            print(f"{len(reports)} HTML raporu yazıldı: {stem}-N{ext}")

    if not args.csv and not args.json and not args.html and not args.quiet:
        print(
            "İpucu: sonuçları kaydetmek için --csv ozet.csv, --json out.json "
            "veya --html rapor.html ekleyin."
        )

    reachable = [r for r in reports if r.reachable]
    if not reachable:
        return 2
    return 0 if all(r.total_score >= 50 for r in reachable) else 1


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if args.batch:
        return _run_batch(args)

    if not args.url:
        print("hata: bir URL veya --batch DOSYA gerekli.", file=sys.stderr)
        return 2

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
                print(f"JSON raporu yazıldı: {args.json}")

    if args.html:
        export_html(report, args.html, brand=args.brand, client=args.client,
                    logo=args.logo, client_logo=args.client_logo)
        if not args.quiet:
            print(f"HTML raporu yazıldı: {args.html}")

    # Exit code reflects reachability and a passing-ish score.
    if not report.reachable:
        return 2
    return 0 if report.total_score >= 50 else 1


if __name__ == "__main__":
    sys.exit(main())
