"""Content-structure analysis for GEO readiness.

Evaluates heading hierarchy (single H1, presence of H2s), the "answer-first"
pattern (a concise answer near the top of the page), and reports on the
presence of an llms.txt file (fetched by the crawler).
"""

from typing import List, Optional

from bs4 import BeautifulSoup

from . import FAIL, OK, WARN, CategoryResult, Finding

MAX_SCORE = 20.0
LLMS_MAX_SCORE = 10.0
META_MAX_SCORE = 10.0

# Sub-weights within meta signals (sum == META_MAX_SCORE).
W_TITLE = 3.5
W_DESCRIPTION = 3.5
W_OG = 3.0

# Reasonable length bounds for title / description.
TITLE_MIN, TITLE_MAX = 15, 65
DESC_MIN, DESC_MAX = 50, 160

# Sub-weights within content structure (sum == MAX_SCORE).
W_SINGLE_H1 = 7.0
W_HAS_H2 = 6.0
W_ANSWER_FIRST = 7.0

# An "answer-first" lead paragraph should be reasonably concise but complete.
ANSWER_MIN_WORDS = 15
ANSWER_MAX_WORDS = 120


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _first_meaningful_paragraph(soup: BeautifulSoup) -> Optional[str]:
    """Return the first substantive <p> appearing after the first H1."""
    h1 = soup.find("h1")
    # Walk forward from the H1 (or from the top if no H1) to find a real <p>.
    start = h1 if h1 else soup
    for p in start.find_all_next("p") if h1 else soup.find_all("p"):
        txt = _text(p)
        if len(txt.split()) >= 5:
            return txt
    return None


def analyze(html: str) -> CategoryResult:
    soup = BeautifulSoup(html or "", "lxml")
    findings: List[Finding] = []
    score = 0.0

    h1s = soup.find_all("h1")
    h2s = soup.find_all("h2")

    # --- Single H1 -------------------------------------------------------
    if len(h1s) == 1:
        score += W_SINGLE_H1
        findings.append(Finding(OK, f"Exactly one H1 found: \"{_truncate(_text(h1s[0]))}\"."))
    elif len(h1s) == 0:
        findings.append(
            Finding(
                FAIL,
                "No H1 heading found.",
                "Add a single, descriptive H1 that states the page's primary topic.",
            )
        )
    else:
        # Partial credit for having at least one, but multiple is an issue.
        score += W_SINGLE_H1 / 2
        findings.append(
            Finding(
                WARN,
                f"Multiple H1 headings found ({len(h1s)}).",
                "Use exactly one H1 per page; demote the rest to H2/H3.",
            )
        )

    # --- H2 hierarchy ----------------------------------------------------
    if len(h2s) >= 2:
        score += W_HAS_H2
        findings.append(Finding(OK, f"{len(h2s)} H2 sub-headings structure the content."))
    elif len(h2s) == 1:
        score += W_HAS_H2 / 2
        findings.append(
            Finding(
                WARN,
                "Only one H2 found.",
                "Break content into multiple H2 sections so AI engines can extract "
                "discrete, citable passages.",
            )
        )
    else:
        findings.append(
            Finding(
                WARN,
                "No H2 sub-headings found.",
                "Add H2 sections to create a clear, extractable content hierarchy.",
            )
        )

    # --- Answer-first pattern -------------------------------------------
    lead = _first_meaningful_paragraph(soup)
    if lead:
        words = len(lead.split())
        if ANSWER_MIN_WORDS <= words <= ANSWER_MAX_WORDS:
            score += W_ANSWER_FIRST
            findings.append(
                Finding(
                    OK,
                    f"Answer-first lead paragraph present ({words} words).",
                )
            )
        elif words < ANSWER_MIN_WORDS:
            score += W_ANSWER_FIRST / 2
            findings.append(
                Finding(
                    WARN,
                    f"Lead paragraph is very short ({words} words).",
                    "Open with a concise but complete answer (≈2-4 sentences) that "
                    "directly addresses the page's core question.",
                )
            )
        else:
            score += W_ANSWER_FIRST / 2
            findings.append(
                Finding(
                    WARN,
                    f"Lead paragraph is long ({words} words) — answer may be buried.",
                    "Lead with a short, direct answer, then expand below it "
                    "(inverted-pyramid / answer-first style).",
                )
            )
    else:
        findings.append(
            Finding(
                FAIL,
                "No substantive lead paragraph detected.",
                "Add an opening paragraph that directly answers the user's likely "
                "question — AI engines favor answer-first content.",
            )
        )

    return CategoryResult(
        key="content",
        name="Content Structure",
        score=min(MAX_SCORE, score),
        max_score=MAX_SCORE,
        findings=findings,
    )


def analyze_llms_txt(found: bool, llms_url: str = "") -> CategoryResult:
    """Score the presence of an llms.txt file (fetched by the crawler)."""
    if found:
        findings = [
            Finding(OK, f"llms.txt found at {llms_url or '/llms.txt'}.")
        ]
        score = LLMS_MAX_SCORE
    else:
        findings = [
            Finding(
                FAIL,
                "No llms.txt found at the site root.",
                "Publish /llms.txt — a curated, LLM-friendly map of your most "
                "important content — to guide AI crawlers to your key pages.",
            )
        ]
        score = 0.0

    return CategoryResult(
        key="llms_txt",
        name="llms.txt",
        score=score,
        max_score=LLMS_MAX_SCORE,
        findings=findings,
    )


def analyze_meta(html: str) -> CategoryResult:
    """Score meta signals: <title>, meta description, and Open Graph tags."""
    soup = BeautifulSoup(html or "", "lxml")
    findings: List[Finding] = []
    score = 0.0

    # --- <title> ---------------------------------------------------------
    title_el = soup.find("title")
    title = _text(title_el)
    if title:
        n = len(title)
        if TITLE_MIN <= n <= TITLE_MAX:
            score += W_TITLE
            findings.append(Finding(OK, f"Title tag present ({n} chars)."))
        else:
            score += W_TITLE / 2
            findings.append(
                Finding(
                    WARN,
                    f"Title length is {n} chars (ideal {TITLE_MIN}-{TITLE_MAX}).",
                    "Tighten the title to a descriptive, keyword-rich phrase within "
                    f"{TITLE_MIN}-{TITLE_MAX} characters.",
                )
            )
    else:
        findings.append(
            Finding(FAIL, "No <title> tag found.", "Add a descriptive <title> tag.")
        )

    # --- meta description ------------------------------------------------
    desc_el = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
    desc = desc_el.get("content", "").strip() if desc_el else ""
    if desc:
        n = len(desc)
        if DESC_MIN <= n <= DESC_MAX:
            score += W_DESCRIPTION
            findings.append(Finding(OK, f"Meta description present ({n} chars)."))
        else:
            score += W_DESCRIPTION / 2
            findings.append(
                Finding(
                    WARN,
                    f"Meta description length is {n} chars (ideal {DESC_MIN}-{DESC_MAX}).",
                    "Write a concise summary within "
                    f"{DESC_MIN}-{DESC_MAX} characters.",
                )
            )
    else:
        findings.append(
            Finding(
                FAIL,
                "No meta description found.",
                "Add a <meta name=\"description\"> summarizing the page.",
            )
        )

    # --- Open Graph ------------------------------------------------------
    og_tags = soup.find_all(
        "meta", attrs={"property": lambda v: v and v.lower().startswith("og:")}
    )
    og_props = {t.get("property", "").lower() for t in og_tags}
    required_og = {"og:title", "og:description", "og:image"}
    present_og = required_og & og_props
    if present_og == required_og:
        score += W_OG
        findings.append(Finding(OK, "Core Open Graph tags present (title, description, image)."))
    elif present_og:
        score += W_OG / 2
        missing = ", ".join(sorted(required_og - present_og))
        findings.append(
            Finding(
                WARN,
                f"Partial Open Graph tags; missing: {missing}.",
                "Add the missing og: tags for better link previews and entity signals.",
            )
        )
    else:
        findings.append(
            Finding(
                WARN,
                "No Open Graph tags found.",
                "Add og:title, og:description and og:image for richer AI/social previews.",
            )
        )

    return CategoryResult(
        key="meta",
        name="Meta Signals",
        score=min(META_MAX_SCORE, score),
        max_score=META_MAX_SCORE,
        findings=findings,
    )


def _truncate(text: str, length: int = 60) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"
