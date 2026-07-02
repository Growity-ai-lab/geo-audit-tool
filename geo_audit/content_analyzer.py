"""Content-structure analysis for GEO readiness.

Evaluates heading hierarchy (single H1, presence of H2s), the "answer-first"
pattern (a concise answer near the top of the page), and reports on the
presence of an llms.txt file (fetched by the crawler).

User-facing finding text is in Turkish (client-facing reports).
"""

import re
from typing import List, Optional

from bs4 import BeautifulSoup

from . import FAIL, OK, WARN, CategoryResult, Finding

MAX_SCORE = 20.0
LLMS_MAX_SCORE = 10.0
META_MAX_SCORE = 10.0

# Sub-weights within content structure (sum == MAX_SCORE).
W_SINGLE_H1 = 7.0
W_HAS_H2 = 6.0
W_ANSWER_FIRST = 7.0

# Sub-weights within llms.txt content-quality scoring (sum == LLMS_MAX_SCORE
# when fully earned). Per https://llmstxt.org: an H1 title, `## Section`
# headings, and markdown links to key pages — not just the file's presence.
W_LLMS_PRESENT = 2.0
W_LLMS_TITLE = 2.0
W_LLMS_SECTION = 1.0
W_LLMS_LINKS = 5.0
LLMS_LINKS_FOR_FULL_CREDIT = 3

LLMS_TITLE_RE = re.compile(r"^\s*#\s+\S", re.MULTILINE)
LLMS_SECTION_RE = re.compile(r"^\s*##\s+\S", re.MULTILINE)
LLMS_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")

# Sub-weights within meta signals (sum == META_MAX_SCORE).
W_TITLE = 3.5
W_DESCRIPTION = 3.5
W_OG = 3.0

# Reasonable length bounds for title / description.
TITLE_MIN, TITLE_MAX = 15, 65
DESC_MIN, DESC_MAX = 50, 160

# An "answer-first" lead paragraph should be reasonably concise but complete.
ANSWER_MIN_WORDS = 15
ANSWER_MAX_WORDS = 120


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _first_meaningful_paragraph(soup: BeautifulSoup) -> Optional[str]:
    """Return the first substantive <p> appearing after the first H1."""
    h1 = soup.find("h1")
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
        findings.append(Finding(OK, f"Tek bir H1 başlığı var: \"{_truncate(_text(h1s[0]))}\"."))
    elif len(h1s) == 0:
        findings.append(
            Finding(
                FAIL,
                "Sayfada H1 başlığı yok.",
                "Sayfanın ana konusunu belirten tek ve açıklayıcı bir H1 başlığı ekleyin.",
            )
        )
    else:
        score += W_SINGLE_H1 / 2
        findings.append(
            Finding(
                WARN,
                f"Birden fazla H1 başlığı var ({len(h1s)} adet).",
                "Sayfa başına tek H1 kullanın; diğerlerini H2/H3'e indirin.",
            )
        )

    # --- H2 hierarchy ----------------------------------------------------
    if len(h2s) >= 2:
        score += W_HAS_H2
        findings.append(Finding(OK, f"{len(h2s)} adet H2 alt başlık içeriği yapılandırıyor."))
    elif len(h2s) == 1:
        score += W_HAS_H2 / 2
        findings.append(
            Finding(
                WARN,
                "Yalnızca bir H2 başlığı var.",
                "İçeriği birden fazla H2 bölümüne ayırın; böylece AI motorları "
                "ayrı ayrı alıntılanabilir pasajlar çıkarabilir.",
            )
        )
    else:
        findings.append(
            Finding(
                WARN,
                "Hiç H2 alt başlığı yok.",
                "Net ve çıkarılabilir bir içerik hiyerarşisi için H2 bölümleri ekleyin.",
            )
        )

    # --- Answer-first pattern -------------------------------------------
    lead = _first_meaningful_paragraph(soup)
    if lead:
        words = len(lead.split())
        if ANSWER_MIN_WORDS <= words <= ANSWER_MAX_WORDS:
            score += W_ANSWER_FIRST
            findings.append(
                Finding(OK, f"Önce-cevap (answer-first) giriş paragrafı mevcut ({words} kelime).")
            )
        elif words < ANSWER_MIN_WORDS:
            score += W_ANSWER_FIRST / 2
            findings.append(
                Finding(
                    WARN,
                    f"Giriş paragrafı çok kısa ({words} kelime).",
                    "Sayfanın ana sorusunu doğrudan yanıtlayan, kısa ama eksiksiz "
                    "(≈2-4 cümle) bir giriş ile başlayın.",
                )
            )
        else:
            score += W_ANSWER_FIRST / 2
            findings.append(
                Finding(
                    WARN,
                    f"Giriş paragrafı uzun ({words} kelime) — cevap kaybolmuş olabilir.",
                    "Önce kısa ve net bir cevap verin, ayrıntıyı altında genişletin "
                    "(ters piramit / önce-cevap yaklaşımı).",
                )
            )
    else:
        findings.append(
            Finding(
                FAIL,
                "Anlamlı bir giriş paragrafı bulunamadı.",
                "Kullanıcının olası sorusunu doğrudan yanıtlayan bir giriş paragrafı "
                "ekleyin — AI motorları önce-cevap içeriği tercih eder.",
            )
        )

    return CategoryResult(
        key="content",
        name="İçerik Yapısı",
        score=min(MAX_SCORE, score),
        max_score=MAX_SCORE,
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
            findings.append(Finding(OK, f"Title etiketi mevcut ({n} karakter)."))
        else:
            score += W_TITLE / 2
            findings.append(
                Finding(
                    WARN,
                    f"Title uzunluğu {n} karakter (ideal {TITLE_MIN}-{TITLE_MAX}).",
                    f"Başlığı {TITLE_MIN}-{TITLE_MAX} karakter aralığında, açıklayıcı "
                    "ve anahtar kelime içeren bir ifadeye sıkıştırın.",
                )
            )
    else:
        findings.append(
            Finding(FAIL, "Title etiketi yok.", "Açıklayıcı bir <title> etiketi ekleyin.")
        )

    # --- meta description ------------------------------------------------
    desc_el = soup.find("meta", attrs={"name": lambda v: v and v.lower() == "description"})
    desc = desc_el.get("content", "").strip() if desc_el else ""
    if desc:
        n = len(desc)
        if DESC_MIN <= n <= DESC_MAX:
            score += W_DESCRIPTION
            findings.append(Finding(OK, f"Meta description mevcut ({n} karakter)."))
        else:
            score += W_DESCRIPTION / 2
            findings.append(
                Finding(
                    WARN,
                    f"Meta description uzunluğu {n} karakter (ideal {DESC_MIN}-{DESC_MAX}).",
                    f"Sayfayı özetleyen {DESC_MIN}-{DESC_MAX} karakterlik kısa bir "
                    "açıklama yazın.",
                )
            )
    else:
        findings.append(
            Finding(
                FAIL,
                "Meta description yok.",
                "Sayfayı özetleyen bir <meta name=\"description\"> ekleyin.",
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
        findings.append(Finding(OK, "Temel Open Graph etiketleri mevcut (title, description, image)."))
    elif present_og:
        score += W_OG / 2
        missing = ", ".join(sorted(required_og - present_og))
        findings.append(
            Finding(
                WARN,
                f"Open Graph etiketleri eksik; eksik olanlar: {missing}.",
                "Daha iyi link önizlemeleri ve varlık (entity) sinyalleri için eksik "
                "og: etiketlerini ekleyin.",
            )
        )
    else:
        findings.append(
            Finding(
                WARN,
                "Open Graph etiketi yok.",
                "Zengin AI/sosyal önizlemeler için og:title, og:description ve "
                "og:image ekleyin.",
            )
        )

    return CategoryResult(
        key="meta",
        name="Meta Sinyalleri",
        score=min(META_MAX_SCORE, score),
        max_score=META_MAX_SCORE,
        findings=findings,
    )


def analyze_llms_txt(
    found: bool, llms_url: str = "", content: str = "", ambiguous: bool = False
) -> CategoryResult:
    """Score an llms.txt file by content, not just presence.

    The https://llmstxt.org convention is an H1 title, then ``## Section``
    headings with markdown links (``- [Title](url): description``) to the
    site's key pages. A file that exists but carries no real links (e.g. an
    empty template dropped by a site generator) is barely more useful to an
    AI crawler than no file at all, so it must not score full marks.

    ``ambiguous`` (only meaningful when ``found`` is False) marks that the
    fetch was blocked/rate-limited (403/429/503) rather than confirming the
    file's absence — a clean 404 stays a firm "not found".
    """
    if not found:
        if ambiguous:
            return CategoryResult(
                key="llms_txt",
                name="llms.txt",
                score=0.0,
                max_score=LLMS_MAX_SCORE,
                findings=[
                    Finding(
                        WARN,
                        "llms.txt erişimi doğrulanamadı — istek engellenmiş/"
                        "kısıtlanmış olabilir (bu denemede beklenmeyen bir yanıt alındı).",
                        "Farklı bir ağdan (veya biraz sonra) tekrar deneyin.",
                        override_key="llms_txt_exists",
                    )
                ],
            )
        return CategoryResult(
            key="llms_txt",
            name="llms.txt",
            score=0.0,
            max_score=LLMS_MAX_SCORE,
            findings=[
                Finding(
                    FAIL,
                    "Site kök dizininde llms.txt bulunamadı.",
                    "/llms.txt yayınlayın — en önemli içeriğinizin LLM dostu, derli toplu "
                    "bir haritası — böylece AI tarayıcılarını kilit sayfalarınıza yönlendirin.",
                )
            ],
        )

    findings = [Finding(OK, f"llms.txt bulundu: {llms_url or '/llms.txt'}.")]
    score = W_LLMS_PRESENT

    has_title = bool(LLMS_TITLE_RE.search(content))
    if has_title:
        score += W_LLMS_TITLE
        findings.append(Finding(OK, "Başlık (H1) mevcut."))
    else:
        findings.append(
            Finding(
                WARN,
                "Dosyada H1 başlık (# Marka/Site Adı) yok.",
                "İlk satıra `# Marka veya Site Adı` ekleyin.",
            )
        )

    has_section = bool(LLMS_SECTION_RE.search(content))
    if has_section:
        score += W_LLMS_SECTION

    links = LLMS_LINK_RE.findall(content)
    link_count = len(links)
    if link_count > 0:
        ratio = min(link_count / LLMS_LINKS_FOR_FULL_CREDIT, 1.0)
        score += W_LLMS_LINKS * ratio
        findings.append(Finding(OK, f"{link_count} içerik linki bulundu."))
    else:
        findings.append(
            Finding(
                FAIL,
                "Dosya boş bir şablon — gerçek içerik linki (- [Başlık](url)) yok.",
                "## Bölüm başlıkları altında en önemli sayfalarınıza (ürün, blog, "
                "dokümantasyon) `- [Başlık](url): açıklama` formatında link ekleyin.",
            )
        )
    if link_count > 0 and not has_section:
        findings.append(
            Finding(
                WARN,
                "Linkler `## Bölüm` başlığı altında gruplanmamış.",
                "Linkleri anlamlı `## Bölüm` başlıkları (ör. Dokümantasyon, Ürünler) "
                "altında gruplayın.",
            )
        )

    return CategoryResult(
        key="llms_txt",
        name="llms.txt",
        score=min(score, LLMS_MAX_SCORE),
        max_score=LLMS_MAX_SCORE,
        findings=findings,
    )


def _truncate(text: str, length: int = 60) -> str:
    return text if len(text) <= length else text[: length - 1] + "…"
