"""Structured-data detection: JSON-LD and schema.org markup.

GEO engines lean heavily on structured data to understand and cite content.
This module detects JSON-LD blocks (and, as a fallback, microdata/RDFa) and
reports which high-value schema.org types are present.
"""

import json
import re
from typing import List, Set

from bs4 import BeautifulSoup

from . import FAIL, OK, WARN, CategoryResult, Finding

# High-value schema types for GEO, mapped to a friendly label.
KEY_TYPES = {
    "faqpage": "FAQPage",
    "organization": "Organization",
    "howto": "HowTo",
    "article": "Article",
}

# Article subtypes that should count toward "Article".
ARTICLE_ALIASES = {"article", "newsarticle", "blogposting", "techarticle", "report"}

MAX_SCORE = 25.0
# Points per detected key type (4 types -> 6.25 each, capped at MAX_SCORE).
POINTS_PER_TYPE = MAX_SCORE / len(KEY_TYPES)


def _collect_types(node, found: Set[str]) -> None:
    """Recursively collect lowercased @type values from a JSON-LD node."""
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str):
            found.add(t.lower())
        elif isinstance(t, list):
            for item in t:
                if isinstance(item, str):
                    found.add(item.lower())
        # @graph and nested entities.
        for value in node.values():
            if isinstance(value, (dict, list)):
                _collect_types(value, found)
    elif isinstance(node, list):
        for item in node:
            _collect_types(item, found)


def extract_jsonld_types(soup: BeautifulSoup) -> Set[str]:
    """Parse all <script type=application/ld+json> blocks and return types."""
    found: Set[str] = set()
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    for script in scripts:
        raw = script.string or script.get_text() or ""
        raw = raw.strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Some sites concatenate multiple JSON objects; try a lenient pass.
            try:
                data = json.loads(re.sub(r"}\s*{", "},{", f"[{raw}]"))
            except json.JSONDecodeError:
                continue
        _collect_types(data, found)
    return found


def extract_microdata_types(soup: BeautifulSoup) -> Set[str]:
    """Fallback: collect schema.org types from microdata itemtype attributes."""
    found: Set[str] = set()
    for el in soup.find_all(attrs={"itemtype": True}):
        itemtype = el.get("itemtype", "")
        if "schema.org" in itemtype:
            found.add(itemtype.rstrip("/").rsplit("/", 1)[-1].lower())
    return found


def _normalize_key_types(found: Set[str]) -> Set[str]:
    """Map raw types to the set of present KEY_TYPES keys."""
    present: Set[str] = set()
    for raw in found:
        if raw in KEY_TYPES:
            present.add(raw)
        elif raw in ARTICLE_ALIASES:
            present.add("article")
    return present


def analyze(html: str) -> CategoryResult:
    soup = BeautifulSoup(html or "", "lxml")

    jsonld_types = extract_jsonld_types(soup)
    micro_types = extract_microdata_types(soup)
    all_types = jsonld_types | micro_types

    present_keys = _normalize_key_types(all_types)
    score = min(MAX_SCORE, len(present_keys) * POINTS_PER_TYPE)

    findings: List[Finding] = []

    has_any_jsonld = bool(soup.find("script", attrs={"type": "application/ld+json"}))
    if not has_any_jsonld and not micro_types:
        findings.append(
            Finding(
                FAIL,
                "No JSON-LD or schema.org structured data found.",
                "Add JSON-LD markup (e.g. Organization + Article) so AI engines "
                "can reliably parse and cite your content.",
            )
        )
    elif not has_any_jsonld and micro_types:
        findings.append(
            Finding(
                WARN,
                "Only microdata found; no JSON-LD blocks detected.",
                "Prefer JSON-LD (<script type=\"application/ld+json\">), the format "
                "most reliably consumed by AI crawlers.",
            )
        )

    # Per-key-type findings.
    for key, label in KEY_TYPES.items():
        if key in present_keys:
            findings.append(
                Finding(OK, f"{label} schema detected.")
            )
        else:
            findings.append(
                Finding(
                    WARN,
                    f"{label} schema not found.",
                    _recommendation_for(key),
                )
            )

    # Surface any other interesting types we picked up.
    extras = sorted(all_types - set(KEY_TYPES) - ARTICLE_ALIASES)
    if extras:
        findings.append(
            Finding(
                OK,
                "Additional structured-data types present: "
                + ", ".join(extras[:8])
                + ("…" if len(extras) > 8 else ""),
            )
        )

    return CategoryResult(
        key="schema",
        name="Schema Markup",
        score=score,
        max_score=MAX_SCORE,
        findings=findings,
    )


def _recommendation_for(key: str) -> str:
    tips = {
        "faqpage": "Add FAQPage schema for Q&A content — strongly favored by AI "
                   "answer engines.",
        "organization": "Add Organization schema (name, logo, sameAs) to establish "
                        "entity identity.",
        "howto": "Add HowTo schema for step-by-step content to improve eligibility "
                 "for AI step extraction.",
        "article": "Add Article schema (headline, author, datePublished) for "
                   "editorial/blog content.",
    }
    return tips.get(key, "Add the relevant schema.org type.")
