"""URL fetching, robots.txt parsing, and AI-bot access control.

This module is responsible for all network I/O. It fetches the target page
once (so other analyzers can reuse the HTML), retrieves robots.txt and
llms.txt, and evaluates whether the major generative-AI crawlers are allowed
to access the page.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from . import FAIL, OK, WARN, CategoryResult, Finding
from .fetcher import DEFAULT_TIMEOUT, DEFAULT_UA, Fetcher, RequestsFetcher

BOT_MAX_SCORE = 25.0
SPEED_MAX_SCORE = 10.0

# Page-speed sub-weights (sum == SPEED_MAX_SCORE).
W_STATUS_OK = 2.0
W_RESPONSE_TIME = 3.0
W_HTTPS = 1.0
W_COMPRESSION = 2.0
W_SITEMAP = 2.0

# Response-time thresholds (milliseconds) for full / partial credit.
FAST_MS = 800
SLOW_MS = 2500

# Core Web Vitals thresholds (Google: good / needs-improvement boundaries).
LCP_GOOD_MS = 2500
LCP_NI_MS = 4000
CLS_GOOD = 0.1
CLS_NI = 0.25
INP_GOOD_MS = 200
INP_NI_MS = 500

# Page-speed sub-weights in PSI mode (sum == SPEED_MAX_SCORE). Crawlability
# anchors stay (status/https/sitemap) but most weight moves to real CWV.
PW_STATUS = 1.0
PW_HTTPS = 1.0
PW_SITEMAP = 1.0
PW_LCP = 3.0
PW_CLS = 2.0
PW_PERF = 2.0

# Generative-AI crawlers we care about for GEO. The values are example
# user-agent strings used when probing robots.txt rules.
AI_BOTS: Dict[str, str] = {
    "GPTBot": "GPTBot",                  # OpenAI
    "ClaudeBot": "ClaudeBot",            # Anthropic
    "PerplexityBot": "PerplexityBot",    # Perplexity
}

def _looks_like_html(text: str) -> bool:
    """True if the body is (most likely) an HTML page, e.g. a soft-404.

    Sidecar files like robots.txt and llms.txt are plain text. Many servers
    answer requests for a missing /llms.txt with a 200 status and an HTML
    page (a "soft 404"), which must NOT be treated as a real file.
    """
    head = (text or "")[:2000].lower()
    return (
        "<!doctype html" in head
        or "<html" in head
        or "<head" in head
        or "<body" in head
    )


@dataclass
class CrawlResult:
    """Everything gathered from the network for a single audit run."""

    url: str
    final_url: str = ""
    status_code: Optional[int] = None
    ok: bool = False
    error: Optional[str] = None

    html: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    elapsed_ms: Optional[float] = None
    content_length: int = 0
    rendered_with: str = "requests"

    robots_found: bool = False
    robots_text: str = ""
    bot_access: Dict[str, bool] = field(default_factory=dict)

    llms_txt_found: bool = False
    llms_txt_url: str = ""

    sitemap_found: bool = False
    sitemap_url: str = ""
    sitemap_url_count: int = 0

    # Real Core Web Vitals from PageSpeed Insights (A5), populated only when a
    # PSI API key is configured. None => fall back to crawlability-only scoring.
    psi_lcp_ms: Optional[float] = None
    psi_cls: Optional[float] = None
    psi_inp_ms: Optional[float] = None
    psi_perf_score: Optional[float] = None
    psi_source: Optional[str] = None

    @property
    def has_psi(self) -> bool:
        """True when real CWV data is available for scoring."""
        return self.psi_source == "psi" and (
            self.psi_perf_score is not None
            or self.psi_lcp_ms is not None
            or self.psi_cls is not None
        )

    @property
    def base_url(self) -> str:
        parts = urlparse(self.final_url or self.url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def is_https(self) -> bool:
        return urlparse(self.final_url or self.url).scheme == "https"


def normalize_url(url: str) -> str:
    """Ensure the URL has a scheme; default to https."""
    url = url.strip()
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


class Crawler:
    """Fetches a page and its sidecar resources (robots.txt, llms.txt)."""

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        user_agent: str = DEFAULT_UA,
        fetcher: Optional[Fetcher] = None,
        psi_api_key: Optional[str] = None,
        psi_strategy: str = "mobile",
    ):
        self.timeout = timeout
        self.psi_api_key = psi_api_key
        self.psi_strategy = psi_strategy
        # Lightweight session reused for sidecar files (robots/llms/sitemap),
        # which are plain text and never need JavaScript rendering.
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            }
        )
        # Pluggable strategy for the main page fetch. Defaults to the original
        # requests-based behaviour, sharing this session.
        self.fetcher: Fetcher = fetcher or RequestsFetcher(
            session=self.session, timeout=timeout
        )

    def crawl(self, url: str) -> CrawlResult:
        url = normalize_url(url)
        result = CrawlResult(url=url)

        # 1. Fetch the main page via the configured strategy.
        try:
            resp = self.fetcher.fetch(url)
            result.elapsed_ms = resp.elapsed_ms
            result.status_code = resp.status_code
            result.final_url = resp.final_url
            result.headers = resp.headers
            result.html = resp.text
            result.content_length = resp.content_length
            result.ok = resp.ok
            result.rendered_with = resp.rendered_with
            if not resp.ok:
                result.error = f"HTTP {resp.status_code}"
        except requests.RequestException as exc:
            result.error = f"Request failed: {exc}"
            return result
        except Exception as exc:  # noqa: BLE001 - browser/transport failures
            # PlaywrightFetcher and other strategies may raise non-requests
            # errors; surface them the same graceful way instead of crashing.
            result.error = f"Fetch failed: {exc}"
            return result

        # 2. robots.txt + AI bot access.
        self._check_robots(result)

        # 3. llms.txt presence.
        self._check_llms_txt(result)

        # 4. sitemap.xml discovery.
        self._check_sitemap(result)

        # 5. Real Core Web Vitals (optional; only when a PSI key is set).
        if self.psi_api_key:
            self._fetch_psi(result)

        return result

    def _fetch_psi(self, result: CrawlResult) -> None:
        """Populate real CWV from PageSpeed Insights (graceful on failure)."""
        from .pagespeed import fetch_psi

        psi = fetch_psi(
            result.final_url or result.url,
            self.psi_api_key,
            strategy=self.psi_strategy,
            timeout=max(self.timeout, 30),
        )
        if psi is None:
            return
        result.psi_lcp_ms = psi.lcp_ms
        result.psi_cls = psi.cls
        result.psi_inp_ms = psi.inp_ms
        result.psi_perf_score = psi.perf_score
        result.psi_source = "psi"

    # ------------------------------------------------------------------ #

    def _fetch_text(self, url: str) -> Optional[requests.Response]:
        try:
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            return resp
        except requests.RequestException:
            return None

    def _check_robots(self, result: CrawlResult) -> None:
        robots_url = urljoin(result.base_url + "/", "robots.txt")
        resp = self._fetch_text(robots_url)

        if (
            resp is not None
            and resp.status_code == 200
            and resp.text.strip()
            and not _looks_like_html(resp.text)  # reject HTML soft-404s
        ):
            result.robots_found = True
            result.robots_text = resp.text
            result.bot_access = self._parse_bot_access(
                resp.text, result.final_url or result.url
            )
        else:
            # No robots.txt => nothing is disallowed; all bots may crawl.
            result.robots_found = False
            result.bot_access = {bot: True for bot in AI_BOTS}

    @staticmethod
    def _parse_bot_access(robots_text: str, target_url: str) -> Dict[str, bool]:
        access: Dict[str, bool] = {}
        for bot, ua in AI_BOTS.items():
            parser = RobotFileParser()
            parser.parse(robots_text.splitlines())
            try:
                access[bot] = parser.can_fetch(ua, target_url)
            except Exception:
                # On any parser quirk, be conservative and assume allowed.
                access[bot] = True
        return access

    def _check_llms_txt(self, result: CrawlResult) -> None:
        result.llms_txt_found = False
        llms_url = urljoin(result.base_url + "/", "llms.txt")
        resp = self._fetch_text(llms_url)
        if resp is None or resp.status_code != 200 or not resp.text.strip():
            return

        content_type = resp.headers.get("Content-Type", "").lower()
        # A real llms.txt is plain text / markdown — never an HTML page.
        # Reject explicit HTML content-types AND bodies that look like HTML
        # (covers soft-404s served as 200 with the wrong/missing content-type).
        if "html" in content_type or _looks_like_html(resp.text):
            return

        result.llms_txt_found = True
        result.llms_txt_url = llms_url

    def _check_sitemap(self, result: CrawlResult) -> None:
        # Prefer a Sitemap: directive in robots.txt, else fall back to the
        # conventional /sitemap.xml location.
        candidates = []
        for line in result.robots_text.splitlines():
            if line.strip().lower().startswith("sitemap:"):
                candidates.append(line.split(":", 1)[1].strip())
        candidates.append(urljoin(result.base_url + "/", "sitemap.xml"))

        for sitemap_url in candidates:
            resp = self._fetch_text(sitemap_url)
            if resp is not None and resp.status_code == 200 and resp.text.strip():
                body = resp.text
                if "<urlset" in body or "<sitemapindex" in body or "<url>" in body:
                    result.sitemap_found = True
                    result.sitemap_url = sitemap_url
                    result.sitemap_url_count = body.count("<loc>")
                    return
        result.sitemap_found = False


def analyze_bot_access(result: CrawlResult) -> CategoryResult:
    """Score whether the major generative-AI crawlers can access the page."""
    findings = []
    access = result.bot_access or {bot: True for bot in AI_BOTS}
    allowed = [bot for bot, ok in access.items() if ok]
    blocked = [bot for bot, ok in access.items() if not ok]

    per_bot = BOT_MAX_SCORE / len(AI_BOTS)
    score = per_bot * len(allowed)

    if not result.robots_found:
        findings.append(
            Finding(
                OK,
                "robots.txt bulunamadı — AI tarayıcıları varsayılan olarak engellenmiyor.",
                "Niyeti netleştirmek için GPTBot, ClaudeBot ve PerplexityBot'a açıkça "
                "izin veren bir robots.txt eklemeyi değerlendirin.",
            )
        )

    for bot in allowed:
        findings.append(Finding(OK, f"{bot} bu sayfayı tarayabiliyor."))
    for bot in blocked:
        findings.append(
            Finding(
                FAIL,
                f"{bot} robots.txt tarafından engelleniyor.",
                f"{bot} için Disallow kuralını kaldırın; böylece bu AI motoru "
                "içeriğinizi indeksleyip alıntılayabilir.",
            )
        )

    return CategoryResult(
        key="bot_access",
        name="AI Bot Erişimi",
        score=score,
        max_score=BOT_MAX_SCORE,
        findings=findings,
    )


def analyze_page_speed(result: CrawlResult) -> CategoryResult:
    """Score the page-speed category.

    With real Core Web Vitals (a PSI key configured) the score is CWV-driven;
    otherwise it falls back to the original crawlability-only signals so the
    behaviour — and the existing tests — are unchanged.
    """
    if result.has_psi:
        return _analyze_page_speed_psi(result)

    findings = []
    score = 0.0

    # Status code.
    if result.status_code == 200:
        score += W_STATUS_OK
        findings.append(Finding(OK, "Sayfa HTTP 200 OK yanıtı veriyor."))
    else:
        findings.append(
            Finding(
                FAIL,
                f"Sayfa HTTP {result.status_code} yanıtı verdi.",
                "Kanonik URL'nin tarayıcılara 200 yanıtı verdiğinden emin olun.",
            )
        )

    # Response time.
    ms = result.elapsed_ms
    if ms is None:
        findings.append(Finding(WARN, "Yanıt süresi ölçülemedi."))
    elif ms <= FAST_MS:
        score += W_RESPONSE_TIME
        findings.append(Finding(OK, f"Hızlı sunucu yanıtı ({ms:.0f} ms)."))
    elif ms <= SLOW_MS:
        score += W_RESPONSE_TIME / 2
        findings.append(
            Finding(
                WARN,
                f"Orta düzey sunucu yanıtı ({ms:.0f} ms).",
                "Tarayıcıların sitenizi kısıtlamaması için < 800 ms TTFB hedefleyin.",
            )
        )
    else:
        findings.append(
            Finding(
                FAIL,
                f"Yavaş sunucu yanıtı ({ms:.0f} ms).",
                "Sunucu yanıt süresini azaltın (önbellek, CDN) — yavaş sayfalar daha "
                "seyrek taranır.",
            )
        )

    # HTTPS.
    if result.is_https:
        score += W_HTTPS
        findings.append(Finding(OK, "HTTPS üzerinden sunuluyor."))
    else:
        findings.append(
            Finding(FAIL, "HTTPS üzerinden sunulmuyor.", "Siteyi HTTPS üzerinden sunun.")
        )

    # Compression.
    encoding = result.headers.get("content-encoding", "").lower()
    if any(enc in encoding for enc in ("gzip", "br", "deflate", "zstd")):
        score += W_COMPRESSION
        findings.append(Finding(OK, f"Yanıt sıkıştırılmış ({encoding})."))
    else:
        findings.append(
            Finding(
                WARN,
                "İçerik sıkıştırması tespit edilmedi.",
                "Daha hızlı teslim için gzip veya Brotli sıkıştırmasını etkinleştirin.",
            )
        )

    # Sitemap.
    if result.sitemap_found:
        score += W_SITEMAP
        count = (
            f" ({result.sitemap_url_count} URL)"
            if result.sitemap_url_count
            else ""
        )
        findings.append(Finding(OK, f"Sitemap bulundu: {result.sitemap_url}{count}."))
    else:
        findings.append(
            Finding(
                WARN,
                "XML sitemap bulunamadı.",
                "Bir sitemap.xml yayınlayın ve robots.txt'den referans verin; böylece "
                "tarayıcılar tüm sayfalarınızı keşfedebilir.",
            )
        )

    return CategoryResult(
        key="page_speed",
        name="Sayfa Hızı / Taranabilirlik",
        score=min(SPEED_MAX_SCORE, score),
        max_score=SPEED_MAX_SCORE,
        findings=findings,
    )


def _analyze_page_speed_psi(result: CrawlResult) -> CategoryResult:
    """Score page speed from real Core Web Vitals (PageSpeed Insights)."""
    findings = []
    score = 0.0

    # Crawlability anchors (kept, reduced weight).
    if result.status_code == 200:
        score += PW_STATUS
        findings.append(Finding(OK, "Sayfa HTTP 200 OK yanıtı veriyor."))
    else:
        findings.append(
            Finding(
                FAIL,
                f"Sayfa HTTP {result.status_code} yanıtı verdi.",
                "Kanonik URL'nin tarayıcılara 200 yanıtı verdiğinden emin olun.",
            )
        )

    if result.is_https:
        score += PW_HTTPS
        findings.append(Finding(OK, "HTTPS üzerinden sunuluyor."))
    else:
        findings.append(
            Finding(FAIL, "HTTPS üzerinden sunulmuyor.", "Siteyi HTTPS üzerinden sunun.")
        )

    if result.sitemap_found:
        score += PW_SITEMAP
        findings.append(Finding(OK, f"Sitemap bulundu: {result.sitemap_url}."))
    else:
        findings.append(
            Finding(
                WARN,
                "XML sitemap bulunamadı.",
                "Bir sitemap.xml yayınlayın ve robots.txt'den referans verin.",
            )
        )

    # Largest Contentful Paint.
    lcp = result.psi_lcp_ms
    if lcp is not None:
        secs = lcp / 1000.0
        if lcp <= LCP_GOOD_MS:
            score += PW_LCP
            findings.append(Finding(OK, f"İyi LCP: {secs:.1f} sn (gerçek ölçüm)."))
        elif lcp <= LCP_NI_MS:
            score += PW_LCP / 2
            findings.append(
                Finding(
                    WARN,
                    f"Geliştirilebilir LCP: {secs:.1f} sn.",
                    "En büyük içerik ögesini hızlandırın (görsel optimizasyonu, "
                    "kritik CSS, sunucu yanıtı) — hedef < 2,5 sn.",
                )
            )
        else:
            findings.append(
                Finding(
                    FAIL,
                    f"Zayıf LCP: {secs:.1f} sn.",
                    "LCP'yi < 2,5 sn'ye indirin; yavaş yükleme AI/araması "
                    "deneyimini ve sıralamayı olumsuz etkiler.",
                )
            )

    # Cumulative Layout Shift.
    cls = result.psi_cls
    if cls is not None:
        if cls <= CLS_GOOD:
            score += PW_CLS
            findings.append(Finding(OK, f"İyi CLS: {cls:.2f} (düzen kaymıyor)."))
        elif cls <= CLS_NI:
            score += PW_CLS / 2
            findings.append(
                Finding(
                    WARN,
                    f"Geliştirilebilir CLS: {cls:.2f}.",
                    "Görsel/iframe boyutlarını sabitleyin, font yüklemesini "
                    "stabilize edin — hedef < 0,1.",
                )
            )
        else:
            findings.append(
                Finding(
                    FAIL,
                    f"Zayıf CLS: {cls:.2f}.",
                    "Beklenmedik düzen kaymalarını giderin (boyutsuz medya, geç "
                    "yüklenen içerik) — hedef < 0,1.",
                )
            )

    # Lighthouse performance score (continuous contribution).
    perf = result.psi_perf_score
    if perf is not None:
        score += PW_PERF * (perf / 100.0)
        sev = OK if perf >= 90 else WARN if perf >= 50 else FAIL
        findings.append(
            Finding(sev, f"Lighthouse performans skoru: {perf:.0f}/100.")
        )

    # Interaction to Next Paint — reported only (field data, not always present).
    inp = result.psi_inp_ms
    if inp is not None:
        sev = OK if inp <= INP_GOOD_MS else WARN if inp <= INP_NI_MS else FAIL
        findings.append(
            Finding(sev, f"INP: {inp:.0f} ms (gerçek kullanıcı etkileşimi).")
        )

    metrics = {
        "lcp_ms": lcp,
        "cls": cls,
        "inp_ms": inp,
        "perf_score": perf,
        "source": "psi",
    }

    return CategoryResult(
        key="page_speed",
        name="Sayfa Hızı / Core Web Vitals",
        score=min(SPEED_MAX_SCORE, score),
        max_score=SPEED_MAX_SCORE,
        findings=findings,
        metrics=metrics,
    )
