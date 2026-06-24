"""URL fetching, robots.txt parsing, and AI-bot access control.

This module is responsible for all network I/O. It fetches the target page
once (so other analyzers can reuse the HTML), retrieves robots.txt and
llms.txt, and evaluates whether the major generative-AI crawlers are allowed
to access the page.
"""

import time
from dataclasses import dataclass, field
from typing import Dict, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

from . import FAIL, OK, WARN, CategoryResult, Finding

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

# Generative-AI crawlers we care about for GEO. The values are example
# user-agent strings used when probing robots.txt rules.
AI_BOTS: Dict[str, str] = {
    "GPTBot": "GPTBot",                  # OpenAI
    "ClaudeBot": "ClaudeBot",            # Anthropic
    "PerplexityBot": "PerplexityBot",    # Perplexity
}

DEFAULT_TIMEOUT = 15
DEFAULT_UA = (
    "Mozilla/5.0 (compatible; GEO-Audit-Tool/0.1; "
    "+https://github.com/growity-ai-lab/geo-audit-tool)"
)


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

    robots_found: bool = False
    robots_text: str = ""
    bot_access: Dict[str, bool] = field(default_factory=dict)

    llms_txt_found: bool = False
    llms_txt_url: str = ""

    sitemap_found: bool = False
    sitemap_url: str = ""
    sitemap_url_count: int = 0

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

    def __init__(self, timeout: int = DEFAULT_TIMEOUT, user_agent: str = DEFAULT_UA):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            }
        )

    def crawl(self, url: str) -> CrawlResult:
        url = normalize_url(url)
        result = CrawlResult(url=url)

        # 1. Fetch the main page.
        try:
            start = time.perf_counter()
            resp = self.session.get(url, timeout=self.timeout, allow_redirects=True)
            result.elapsed_ms = (time.perf_counter() - start) * 1000.0
            result.status_code = resp.status_code
            result.final_url = resp.url
            result.headers = {k.lower(): v for k, v in resp.headers.items()}
            result.html = resp.text or ""
            result.content_length = len(resp.content or b"")
            result.ok = resp.ok
            if not resp.ok:
                result.error = f"HTTP {resp.status_code}"
        except requests.RequestException as exc:
            result.error = f"Request failed: {exc}"
            return result

        # 2. robots.txt + AI bot access.
        self._check_robots(result)

        # 3. llms.txt presence.
        self._check_llms_txt(result)

        # 4. sitemap.xml discovery.
        self._check_sitemap(result)

        return result

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
    """Score basic crawlability signals from the HTTP response."""
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
