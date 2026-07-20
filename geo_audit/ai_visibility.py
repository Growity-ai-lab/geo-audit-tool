"""AI Visibility: does the brand show up in LLM answers, and is it cited?

A *separate* analysis from the on-page GEO score (kept out of the 0-100 on
purpose — it measures an off-site outcome, and LLM answers are
non-deterministic). For a brand + domain we build a set of prompts, run each
across the configured LLM engines a few times (sampling), and measure:

  - is the brand **mentioned** in the answer?
  - is the domain **cited** as a source?
  - which **competitors** and **sources** show up?

Engines and the competitor extractor are *injected* (Protocols) so this module
stays pure and unit-testable; the real network adapters live in
``geo_audit/ai_engines.py``. Every external call is counted and bounded by a
budget cap (LLM calls cost real money).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Protocol, Tuple
from urllib.parse import urlparse

from .scorer import grade_for
from .targeting import _tr_fold

logger = logging.getLogger("geo_audit.ai_visibility")

# Weights for the 0-100 visibility score. Citations are scarcer and stronger
# than a bare mention, so they carry more weight per occurrence.
W_MENTION = 0.6
W_CITATION = 0.4


# --------------------------------------------------------------------------- #
# Injected collaborators (real implementations in ai_engines.py)
# --------------------------------------------------------------------------- #


@dataclass
class EngineQueryResult:
    """Raw output of a single LLM engine call."""

    text: str
    sources: List[str] = field(default_factory=list)  # cited URLs / domains


class Engine(Protocol):
    name: str        # display name, e.g. "ChatGPT"
    model: str       # model id used, e.g. "gpt-4o"

    def query(self, prompt: str) -> EngineQueryResult: ...


class CompetitorExtractor(Protocol):
    def extract(self, response_text: str, brand: str) -> List[str]: ...


# --------------------------------------------------------------------------- #
# Result data model
# --------------------------------------------------------------------------- #


@dataclass
class EngineResult:
    """One engine's aggregated result for one prompt (over N samples)."""

    engine: str
    samples: int
    mention_count: int          # samples where the brand was mentioned
    citation_count: int         # samples where the domain was cited
    response_excerpt: str       # a representative answer (first sample)
    competitors: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)

    @property
    def mentioned(self) -> bool:
        return self.mention_count > 0

    @property
    def cited(self) -> bool:
        return self.citation_count > 0

    @property
    def status(self) -> str:
        if self.cited:
            return "cited"
        if self.mentioned:
            return "mentioned"
        return "absent"

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "samples": self.samples,
            "mention_count": self.mention_count,
            "citation_count": self.citation_count,
            "status": self.status,
            "response_excerpt": self.response_excerpt,
            "competitors": self.competitors,
            "sources": self.sources,
        }


@dataclass
class PromptResult:
    prompt: str
    source: str  # 'auto' | 'manual'
    engines: List[EngineResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "prompt": self.prompt,
            "source": self.source,
            "engines": [e.to_dict() for e in self.engines],
        }


@dataclass
class VisibilityReport:
    brand: str
    domain: str
    score: float
    grade: str
    prompt_count: int
    sample_count: int
    engines_used: List[str]
    mention_total: int
    citation_total: int
    slot_total: int              # prompt × engine result count (denominator)
    competitor_ranking: List[dict]
    source_ranking: List[dict]
    engine_stats: List[dict]
    prompts: List[dict]
    api_calls: int               # total external calls made (cost transparency)
    models_used: dict            # engine name -> model id
    generated_at: str

    def to_dict(self) -> dict:
        return {
            "brand": self.brand,
            "domain": self.domain,
            "score": round(self.score, 1),
            "grade": self.grade,
            "prompt_count": self.prompt_count,
            "sample_count": self.sample_count,
            "engines_used": self.engines_used,
            "mention_total": self.mention_total,
            "citation_total": self.citation_total,
            "slot_total": self.slot_total,
            "competitor_ranking": self.competitor_ranking,
            "source_ranking": self.source_ranking,
            "engine_stats": self.engine_stats,
            "prompts": self.prompts,
            "api_calls": self.api_calls,
            "models_used": self.models_used,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "VisibilityReport":
        return cls(
            brand=data["brand"],
            domain=data["domain"],
            score=data["score"],
            grade=data["grade"],
            prompt_count=data["prompt_count"],
            sample_count=data["sample_count"],
            engines_used=data.get("engines_used", []),
            mention_total=data.get("mention_total", 0),
            citation_total=data.get("citation_total", 0),
            slot_total=data.get("slot_total", 0),
            competitor_ranking=data.get("competitor_ranking", []),
            source_ranking=data.get("source_ranking", []),
            engine_stats=data.get("engine_stats", []),
            prompts=data.get("prompts", []),
            api_calls=data.get("api_calls", 0),
            models_used=data.get("models_used", {}),
            generated_at=data.get("generated_at", ""),
        )


# --------------------------------------------------------------------------- #
# Detection helpers (pure)
# --------------------------------------------------------------------------- #


def is_mentioned(text: str, brand: str, aliases: Tuple[str, ...] = ()) -> bool:
    """True if the brand (or an alias) appears in the answer (Turkish-aware)."""
    folded = _tr_fold(text or "")
    for name in (brand, *aliases):
        if name and name.strip() and _tr_fold(name) in folded:
            return True
    return False


def root_domain(url_or_domain: str) -> str:
    """Reduce a URL or host to its registrable-ish root (last two labels)."""
    s = (url_or_domain or "").strip().lower()
    if not s:
        return ""
    if "//" not in s:
        s = "http://" + s
    host = urlparse(s).netloc or ""
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    host = host.split(":")[0]  # drop port
    parts = [p for p in host.split(".") if p]
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def is_cited(sources: List[str], domain: str) -> bool:
    """True if the audited domain appears among the answer's cited sources."""
    ours = root_domain(domain)
    if not ours:
        return False
    return any(root_domain(s) == ours for s in (sources or []))


# --------------------------------------------------------------------------- #
# Prompt generation
# --------------------------------------------------------------------------- #

# Auto prompt templates (Turkish). {brand}/{topic} filled in. Kept generic so
# they read like real user questions an LLM would answer.
_AUTO_TEMPLATES = [
    "{topic} sunan firmalar hangileri?",
    "Türkiye'de {topic} için en iyi firmalar nelerdir?",
    "{brand} hakkında ne biliyorsun?",
    "{brand} ile rakip firmalar arasındaki fark nedir?",
    "{topic} için önerdiğin çözümler ve markalar nelerdir?",
    "{topic} fiyatlandırması nasıl yapılır, hangi firmalar öne çıkıyor?",
]


def build_prompts(
    brand: str,
    topic: str = "",
    manual_prompts: Optional[List[str]] = None,
    max_prompts: int = 10,
) -> List[Tuple[str, str]]:
    """Return a capped list of (prompt, source) with source in {auto, manual}.

    Manual prompts come first (the operator asked for them explicitly); auto
    prompts fill the rest up to ``max_prompts``. ``topic`` defaults to the
    brand when not given.
    """
    topic = (topic or brand).strip()
    out: List[Tuple[str, str]] = []
    seen = set()

    for p in manual_prompts or []:
        p = (p or "").strip()
        key = _tr_fold(p)
        if p and key not in seen:
            out.append((p, "manual"))
            seen.add(key)

    for tmpl in _AUTO_TEMPLATES:
        if len(out) >= max_prompts:
            break
        p = tmpl.format(brand=brand, topic=topic)
        key = _tr_fold(p)
        if key not in seen:
            out.append((p, "auto"))
            seen.add(key)

    return out[:max_prompts]


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def score_visibility(prompt_results: List[PromptResult]) -> float:
    """0-100 from mention/citation rates over all (prompt × engine) slots."""
    slots = [e for pr in prompt_results for e in pr.engines]
    if not slots:
        return 0.0
    mention_rate = sum(1 for e in slots if e.mentioned) / len(slots)
    citation_rate = sum(1 for e in slots if e.cited) / len(slots)
    return 100.0 * (W_MENTION * mention_rate + W_CITATION * citation_rate)


def _rank_competitors(prompt_results: List[PromptResult], limit: int = 8) -> List[dict]:
    counts: dict = {}
    for pr in prompt_results:
        for e in pr.engines:
            for name in set(e.competitors):
                counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [{"name": n, "count": c} for n, c in ranked[:limit]]


def _rank_sources(
    prompt_results: List[PromptResult], domain: str, limit: int = 8
) -> List[dict]:
    ours = root_domain(domain)
    counts: dict = {}
    for pr in prompt_results:
        for e in pr.engines:
            for s in e.sources:
                d = root_domain(s)
                if d:
                    counts[d] = counts.get(d, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    return [
        {"domain": d, "count": c, "is_ours": d == ours} for d, c in ranked[:limit]
    ]


def analyze_visibility(
    *,
    brand: str,
    domain: str,
    prompts: List[Tuple[str, str]],
    engines: List[Engine],
    extractor: Optional[CompetitorExtractor] = None,
    sample_count: int = 2,
    max_api_calls: Optional[int] = None,
    aliases: Tuple[str, ...] = (),
    generated_at: Optional[str] = None,
) -> VisibilityReport:
    """Run every prompt across every engine ``sample_count`` times and roll up.

    External calls (engine queries + competitor extraction) are counted and
    hard-capped at ``max_api_calls`` — once the cap is hit, remaining calls are
    skipped (the partial result is still returned). A single engine raising is
    logged and skipped; it never sinks the run.
    """
    api_calls = 0
    prompt_results: List[PromptResult] = []

    def _over_budget() -> bool:
        return max_api_calls is not None and api_calls >= max_api_calls

    for ptext, psource in prompts:
        eng_results: List[EngineResult] = []
        for eng in engines:
            mention_ct = 0
            citation_ct = 0
            excerpt = ""
            competitors: set = set()
            sources: set = set()
            samples_done = 0

            for i in range(sample_count):
                if _over_budget():
                    break
                api_calls += 1
                try:
                    res = eng.query(ptext)
                except Exception:  # noqa: BLE001 - one engine call must not crash the run
                    logger.exception("engine %s failed on prompt: %s", eng.name, ptext)
                    continue
                samples_done += 1
                if not excerpt:
                    excerpt = (res.text or "")[:600]
                if is_mentioned(res.text, brand, aliases):
                    mention_ct += 1
                if is_cited(res.sources, domain):
                    citation_ct += 1
                for s in res.sources or []:
                    if s:
                        sources.add(s)
                # Competitor extraction: once per (prompt, engine), on the first
                # sample only (cost control), and only if an extractor is given.
                if extractor is not None and i == 0 and not _over_budget():
                    api_calls += 1
                    try:
                        for c in extractor.extract(res.text, brand):
                            c = (c or "").strip()
                            if c and _tr_fold(c) != _tr_fold(brand):
                                competitors.add(c)
                    except Exception:  # noqa: BLE001
                        logger.exception("competitor extraction failed")

            if samples_done == 0:
                continue  # engine unavailable for this prompt; omit
            eng_results.append(
                EngineResult(
                    engine=eng.name,
                    samples=samples_done,
                    mention_count=mention_ct,
                    citation_count=citation_ct,
                    response_excerpt=excerpt,
                    competitors=sorted(competitors),
                    sources=sorted(sources),
                )
            )
        prompt_results.append(PromptResult(ptext, psource, eng_results))

    score = score_visibility(prompt_results)
    slots = [e for pr in prompt_results for e in pr.engines]
    engine_stats = _engine_stats(engines, prompt_results)

    return VisibilityReport(
        brand=brand,
        domain=domain,
        score=score,
        grade=grade_for(score),
        prompt_count=len(prompt_results),
        sample_count=sample_count,
        engines_used=[e.name for e in engines],
        mention_total=sum(1 for e in slots if e.mentioned),
        citation_total=sum(1 for e in slots if e.cited),
        slot_total=len(slots),
        competitor_ranking=_rank_competitors(prompt_results),
        source_ranking=_rank_sources(prompt_results, domain),
        engine_stats=engine_stats,
        prompts=[pr.to_dict() for pr in prompt_results],
        api_calls=api_calls,
        models_used={e.name: getattr(e, "model", "") for e in engines},
        generated_at=generated_at or datetime.now().strftime("%d.%m.%Y %H:%M"),
    )


def _engine_stats(
    engines: List[Engine], prompt_results: List[PromptResult]
) -> List[dict]:
    stats = []
    for eng in engines:
        results = [e for pr in prompt_results for e in pr.engines if e.engine == eng.name]
        stats.append(
            {
                "engine": eng.name,
                "mention_count": sum(1 for e in results if e.mentioned),
                "citation_count": sum(1 for e in results if e.cited),
                "answered": len(results),
            }
        )
    return stats
