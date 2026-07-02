"""Page-type-aware, target-focused analysis (the "Hedefleme" overlay).

This is a *separate* layer from the 100-point GEO score, kept out of it on
purpose so scores stay comparable across page types and keywords (the same
reasoning the plan applied to AI Visibility). It answers three targeted
questions a single-page audit benefits from:

  1. Is the page's target keyword actually present where it matters
     (title, H1, description, lead, subheadings, body)?  → coverage sub-score
  2. Does the page carry the schema types expected for its kind (a product
     page → Product, a blog post → Article/FAQ, …)?      → advisory findings
  3. Is there a FAQ (schema or on-page), which AI answer engines favour?

Pure and side-effect free, like scorer/aggregate/overrides.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from bs4 import BeautifulSoup

from . import FAIL, OK, WARN
from .schema_checker import extract_jsonld_types, extract_microdata_types

# Page types and their Turkish labels (shown in the UI + report).
PAGE_TYPES = {
    "generic": "Genel",
    "homepage": "Ana Sayfa",
    "category": "Kategori",
    "product": "Ürün",
    "blog": "Blog / Makale",
}

# schema.org types (lowercased) expected for each page type, each with a
# friendly label. "generic" expects nothing specific.
EXPECTED_SCHEMAS = {
    "homepage": [("organization", "Organization"), ("website", "WebSite")],
    "category": [("itemlist", "ItemList"), ("breadcrumblist", "BreadcrumbList")],
    "product": [
        ("product", "Product"),
        ("offer", "Offer"),
        ("aggregaterating", "AggregateRating"),
    ],
    "blog": [
        ("article", "Article"),
        ("faqpage", "FAQPage"),
    ],
    "generic": [],
}

# Article subtypes that satisfy an "article" expectation.
_ARTICLE_ALIASES = {"article", "newsarticle", "blogposting", "techarticle", "report"}

# Keyword-coverage locations and their weights (sum == 100).
_KEYWORD_WEIGHTS = [
    ("title", "Sayfa başlığı (title)", 25),
    ("h1", "Ana başlık (H1)", 25),
    ("description", "Meta açıklaması", 15),
    ("lead", "Giriş paragrafı", 15),
    ("headings", "Alt başlıklar (H2/H3)", 10),
    ("body", "Gövde metni", 10),
]


@dataclass
class TargetingReport:
    page_type: str
    page_type_label: str
    target_keyword: str
    # 0-100 keyword-coverage score, or None when no keyword was given.
    keyword_score: Optional[float] = None
    # One row per _KEYWORD_WEIGHTS location: {key, label, present, weight}.
    keyword_checks: List[dict] = field(default_factory=list)
    # Expected schema types for this page type: {type, label, present}.
    schema_expectations: List[dict] = field(default_factory=list)
    faq_present: bool = False
    # Advisory findings (severity, message, recommendation) — do NOT affect the
    # GEO score; they surface targeted opportunities.
    findings: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "page_type": self.page_type,
            "page_type_label": self.page_type_label,
            "target_keyword": self.target_keyword,
            "keyword_score": (
                round(self.keyword_score, 1) if self.keyword_score is not None else None
            ),
            "keyword_checks": self.keyword_checks,
            "schema_expectations": self.schema_expectations,
            "faq_present": self.faq_present,
            "findings": self.findings,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TargetingReport":
        return cls(
            page_type=data["page_type"],
            page_type_label=data.get("page_type_label", data["page_type"]),
            target_keyword=data.get("target_keyword", ""),
            keyword_score=data.get("keyword_score"),
            keyword_checks=data.get("keyword_checks", []),
            schema_expectations=data.get("schema_expectations", []),
            faq_present=data.get("faq_present", False),
            findings=data.get("findings", []),
        )


def _tr_fold(text: str) -> str:
    """Turkish-aware lowercasing for case-insensitive matching.

    Python's ``lower``/``casefold`` use the invariant rules, which map the
    dotless "I" to a dotted "i" — so "BALIĞI" and "balığı" wouldn't match.
    Apply the Turkish special cases (I→ı, İ→i) before lowering the rest."""
    return (text or "").replace("İ", "i").replace("I", "ı").lower()


def _contains(haystack: str, needle: str) -> bool:
    """Case-insensitive substring match (Turkish-aware)."""
    return bool(needle) and _tr_fold(needle) in _tr_fold(haystack)


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _lead_paragraph(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    candidates = h1.find_all_next("p") if h1 else soup.find_all("p")
    for p in candidates:
        txt = _text(p)
        if len(txt.split()) >= 5:  # skip tiny/boilerplate paragraphs
            return txt
    return ""


def _keyword_coverage(soup: BeautifulSoup, keyword: str) -> tuple:
    """Return (checks, score) for keyword presence across key locations."""
    title = _text(soup.find("title"))
    h1 = _text(soup.find("h1"))
    desc_el = soup.find(
        "meta", attrs={"name": lambda v: v and v.lower() == "description"}
    )
    description = desc_el.get("content", "") if desc_el else ""
    lead = _lead_paragraph(soup)
    headings = " ".join(_text(h) for h in soup.find_all(["h2", "h3"]))
    body = _text(soup.find("body") or soup)

    location_text = {
        "title": title,
        "h1": h1,
        "description": description,
        "lead": lead,
        "headings": headings,
        "body": body,
    }

    checks: List[dict] = []
    score = 0.0
    for key, label, weight in _KEYWORD_WEIGHTS:
        present = _contains(location_text[key], keyword)
        if present:
            score += weight
        checks.append(
            {"key": key, "label": label, "present": present, "weight": weight}
        )
    return checks, score


def _detect_faq(soup: BeautifulSoup, all_types: set) -> bool:
    """FAQ present if FAQPage schema exists, or an on-page Q&A pattern shows."""
    if "faqpage" in all_types or "qapage" in all_types:
        return True
    # On-page heuristic: several question-like subheadings (end with "?").
    questions = [
        h for h in soup.find_all(["h2", "h3", "summary", "dt"])
        if _text(h).strip().endswith("?")
    ]
    return len(questions) >= 2


def analyze_targeting(
    html: str, page_type: str = "generic", target_keyword: str = ""
) -> TargetingReport:
    """Build the targeting overlay for a single page.

    ``page_type`` selects the expected-schema set; ``target_keyword`` (optional)
    drives the coverage sub-score. Never affects the GEO score."""
    page_type = page_type if page_type in PAGE_TYPES else "generic"
    keyword = (target_keyword or "").strip()
    soup = BeautifulSoup(html or "", "lxml")

    all_types = extract_jsonld_types(soup) | extract_microdata_types(soup)
    # Normalize article subtypes so an "article" expectation is satisfied.
    if all_types & _ARTICLE_ALIASES:
        all_types = all_types | {"article"}

    findings: List[dict] = []

    # --- Keyword coverage ------------------------------------------------
    keyword_score: Optional[float] = None
    keyword_checks: List[dict] = []
    if keyword:
        keyword_checks, keyword_score = _keyword_coverage(soup, keyword)
        missing = [c["label"] for c in keyword_checks if not c["present"]]
        if keyword_score >= 80:
            findings.append({
                "severity": OK,
                "message": f"Hedef kelime \"{keyword}\" kilit alanlarda güçlü şekilde yer alıyor.",
                "recommendation": "",
            })
        else:
            # Prioritize the two highest-weight missing locations.
            top_missing = [
                c["label"] for c in sorted(
                    (c for c in keyword_checks if not c["present"]),
                    key=lambda c: -c["weight"],
                )
            ][:2]
            findings.append({
                "severity": FAIL if keyword_score < 40 else WARN,
                "message": (
                    f"Hedef kelime \"{keyword}\" kapsamı düşük "
                    f"({keyword_score:.0f}/100); eksik: {', '.join(missing)}."
                ),
                "recommendation": (
                    "Hedef kelimeyi özellikle "
                    + (", ".join(top_missing) if top_missing else "kilit alanlarda")
                    + " içine doğal biçimde yerleştirin."
                ),
            })

    # --- Page-type schema expectations -----------------------------------
    schema_expectations: List[dict] = []
    for stype, label in EXPECTED_SCHEMAS.get(page_type, []):
        present = stype in all_types
        schema_expectations.append({"type": stype, "label": label, "present": present})
        if not present:
            findings.append({
                "severity": WARN,
                "message": f"{PAGE_TYPES[page_type]} sayfası için {label} şeması önerilir — bulunamadı.",
                "recommendation": _schema_tip(stype, label),
            })
    present_labels = [e["label"] for e in schema_expectations if e["present"]]
    if present_labels:
        findings.append({
            "severity": OK,
            "message": (
                f"{PAGE_TYPES[page_type]} için beklenen şemalar mevcut: "
                + ", ".join(present_labels) + "."
            ),
            "recommendation": "",
        })

    # --- FAQ -------------------------------------------------------------
    faq_present = _detect_faq(soup, all_types)
    faq_valued = page_type in ("blog", "product", "category", "homepage")
    if faq_present:
        findings.append({
            "severity": OK,
            "message": "FAQ yapısı tespit edildi (şema veya sayfa içi soru-cevap).",
            "recommendation": "",
        })
    elif faq_valued:
        findings.append({
            "severity": WARN,
            "message": "FAQ (soru-cevap) yapısı bulunamadı.",
            "recommendation": (
                "Sık sorulan sorulardan bir FAQ bölümü + FAQPage şeması ekleyin — "
                "AI cevap motorları soru-cevap içeriğini güçlü şekilde tercih eder."
            ),
        })

    return TargetingReport(
        page_type=page_type,
        page_type_label=PAGE_TYPES[page_type],
        target_keyword=keyword,
        keyword_score=keyword_score,
        keyword_checks=keyword_checks,
        schema_expectations=schema_expectations,
        faq_present=faq_present,
        findings=findings,
    )


def _schema_tip(stype: str, label: str) -> str:
    tips = {
        "organization": "Organization şeması ekleyin (name, logo, sameAs).",
        "website": "WebSite şeması ekleyin (SearchAction ile site içi arama).",
        "itemlist": "Listelenen öğeler için ItemList şeması ekleyin.",
        "breadcrumblist": "Gezinme için BreadcrumbList şeması ekleyin.",
        "product": "Ürün için Product şeması ekleyin (name, image, offers).",
        "offer": "Fiyat/stok için Offer şeması ekleyin (price, availability).",
        "aggregaterating": "Değerlendirmeler için AggregateRating şeması ekleyin.",
        "article": "Article şeması ekleyin (headline, author, datePublished).",
        "faqpage": "Soru-cevap için FAQPage şeması ekleyin.",
    }
    return tips.get(stype, f"{label} şemasını ekleyin.")
