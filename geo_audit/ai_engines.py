"""Real LLM engine adapters for AI Visibility (network layer).

Each adapter implements the ``Engine`` protocol from ``ai_visibility`` —
``query(prompt) -> EngineQueryResult(text, sources)`` — with web search /
grounding enabled so answers reflect what a real user would get, and so cited
sources can be detected. SDK imports are lazy (inside ``query``) so importing
this module never requires the providers' packages to be installed, and a
missing/broken provider degrades to an empty result rather than crashing.

These make real, paid API calls and can only be verified end-to-end with live
keys; the unit tests exercise the response-parsing logic against mocked SDK
objects. Everything is constructed via ``build_engines`` from whichever API
keys are configured (config-gated, like PSI).
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

import requests

from .ai_visibility import EngineQueryResult

logger = logging.getLogger("geo_audit.ai_engines")

_TIMEOUT = 40


class OpenAIEngine:
    """ChatGPT (OpenAI) via the Responses API with the web_search tool."""

    name = "ChatGPT"

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        self.api_key = api_key
        self.model = model

    def query(self, prompt: str) -> EngineQueryResult:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        resp = client.responses.create(
            model=self.model,
            tools=[{"type": "web_search"}],
            input=prompt,
        )
        text = getattr(resp, "output_text", "") or ""
        sources: List[str] = []
        # URL citations are attached as annotations on the message content.
        for item in getattr(resp, "output", []) or []:
            for content in getattr(item, "content", []) or []:
                for ann in getattr(content, "annotations", []) or []:
                    url = getattr(ann, "url", None)
                    if url:
                        sources.append(url)
        return EngineQueryResult(text=text, sources=_dedupe(sources))


class PerplexityEngine:
    """Perplexity (Sonar) — inherently web-grounded, returns citations.

    Uses the REST API directly (rather than the OpenAI-compatible client) so
    the top-level ``citations`` array is read reliably.
    """

    name = "Perplexity"

    def __init__(self, api_key: str, model: str = "sonar"):
        self.api_key = api_key
        self.model = model

    def query(self, prompt: str) -> EngineQueryResult:
        resp = requests.post(
            "https://api.perplexity.ai/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, "messages": [{"role": "user", "content": prompt}]},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
        text = ""
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            pass
        # Perplexity returns citations as a top-level list of URLs (and, newer,
        # a list of {url,...} under search_results).
        sources: List[str] = []
        for c in data.get("citations") or []:
            sources.append(c if isinstance(c, str) else c.get("url", ""))
        for r in data.get("search_results") or []:
            if isinstance(r, dict) and r.get("url"):
                sources.append(r["url"])
        return EngineQueryResult(text=text, sources=_dedupe([s for s in sources if s]))


class GeminiEngine:
    """Gemini (Google) with Google Search grounding.

    Google retires dated model IDs (``gemini-2.0-flash`` etc.) for new keys
    fairly aggressively, so a hard-coded model can start returning 404. If the
    configured model 404s, we discover a live ``generateContent``-capable Flash
    model once via ``models.list()`` and retry — self-healing against future
    renames. The resolved model is cached on the instance."""

    name = "Gemini"

    def __init__(self, api_key: str, model: str = "gemini-flash-latest"):
        self.api_key = api_key
        self.model = model
        self._resolved_model: Optional[str] = None

    def query(self, prompt: str) -> EngineQueryResult:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=self.api_key)
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
        model = self._resolved_model or self.model
        try:
            resp = client.models.generate_content(
                model=model, contents=prompt, config=config
            )
        except Exception as exc:  # noqa: BLE001
            # Only try to recover once, and only from a "model not found".
            if self._resolved_model is not None or not _is_model_not_found(exc):
                raise
            alt = _discover_gemini_model(client)
            if not alt or alt == model:
                raise
            logger.warning("Gemini model %s unavailable; falling back to %s", model, alt)
            self._resolved_model = alt
            resp = client.models.generate_content(
                model=alt, contents=prompt, config=config
            )
        text = getattr(resp, "text", "") or ""
        sources: List[str] = []
        for cand in getattr(resp, "candidates", []) or []:
            gm = getattr(cand, "grounding_metadata", None)
            for chunk in getattr(gm, "grounding_chunks", []) or []:
                web = getattr(chunk, "web", None)
                uri = getattr(web, "uri", None)
                if uri:
                    sources.append(uri)
        return EngineQueryResult(text=text, sources=_dedupe(sources))


def _is_model_not_found(exc: Exception) -> bool:
    low = str(exc).lower()
    return "not_found" in low or "404" in low


# Model IDs that exist but aren't general text chat models (image/audio/tts/
# embedding/etc.) — never auto-pick these for a grounded text answer.
_GEMINI_SKIP = (
    "tts", "image", "embedding", "vision", "audio", "aqa", "imagen", "veo",
    "lyria", "robotics", "computer-use", "gemma", "nano", "deep-research",
    "antigravity",
)


def _model_supports_generate(m) -> bool:
    for attr in ("supported_actions", "supported_generation_methods"):
        vals = getattr(m, attr, None)
        if vals:
            return "generateContent" in vals
    return True  # unknown → assume yes (better to try than to skip)


def _discover_gemini_model(client) -> Optional[str]:
    """Pick a live generateContent-capable Flash model from the account.

    Preference: a ``flash``+``latest`` alias (rename-proof) → any Flash →
    any ``latest`` alias → any candidate. Returns the id without the
    ``models/`` prefix, or None if discovery fails."""
    try:
        models = list(client.models.list())
    except Exception:  # noqa: BLE001
        return None
    names: List[str] = []
    for m in models:
        short = (getattr(m, "name", "") or "").replace("models/", "")
        low = short.lower()
        if not short or any(s in low for s in _GEMINI_SKIP):
            continue
        if not _model_supports_generate(m):
            continue
        names.append(short)
    preferences = (
        lambda n: "flash" in n and "latest" in n and "lite" not in n,
        lambda n: "flash" in n and "lite" not in n,
        lambda n: "latest" in n,
        lambda n: True,
    )
    for pred in preferences:
        for n in names:
            if pred(n.lower()):
                return n
    return None


class ClaudeEngine:
    """Claude (Anthropic) with the web search tool. Optional / off by default."""

    name = "Claude"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5",
        tool_type: str = "web_search_20250305",
    ):
        self.api_key = api_key
        self.model = model
        self.tool_type = tool_type

    def query(self, prompt: str) -> EngineQueryResult:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=1024,
            tools=[{"type": self.tool_type, "name": "web_search"}],
            messages=[{"role": "user", "content": prompt}],
        )
        text_parts: List[str] = []
        sources: List[str] = []
        for block in resp.content or []:
            btype = getattr(block, "type", None)
            if btype == "text":
                text_parts.append(getattr(block, "text", "") or "")
                for cit in getattr(block, "citations", []) or []:
                    url = getattr(cit, "url", None)
                    if url:
                        sources.append(url)
            elif btype == "web_search_tool_result":
                for r in getattr(block, "content", []) or []:
                    url = getattr(r, "url", None)
                    if url:
                        sources.append(url)
        return EngineQueryResult(text="".join(text_parts), sources=_dedupe(sources))


def _dedupe(items: List[str]) -> List[str]:
    return list(dict.fromkeys(i for i in items if i))


# --------------------------------------------------------------------------- #
# Competitor extraction (LLM-based)
# --------------------------------------------------------------------------- #


_EXTRACT_SYSTEM = (
    "Sana bir yapay zeka asistanının yanıtı verilecek. Bu yanıtta adı geçen "
    "ŞİRKET / MARKA isimlerini çıkar. Yalnızca gerçek firma/marka adlarını al; "
    "genel terimleri, ürün kategorilerini, şehir/ülke adlarını dahil etme. "
    'Verilen "{brand}" markasını listeye EKLEME. Sonucu yalnızca JSON dizisi '
    'olarak döndür, ör: ["ABB", "KUKA"].'
)


class OpenAICompetitorExtractor:
    """Extract competitor brand names from a response using a cheap OpenAI call."""

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key
        self.model = model

    def extract(self, response_text: str, brand: str) -> List[str]:
        from openai import OpenAI

        client = OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM.format(brand=brand)},
                {"role": "user", "content": (response_text or "")[:4000]},
            ],
            response_format={"type": "json_object"},
        )
        return _parse_names(resp.choices[0].message.content, brand)


class AnthropicCompetitorExtractor:
    """Extract competitor brand names using a cheap Anthropic call."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5"):
        self.api_key = api_key
        self.model = model

    def extract(self, response_text: str, brand: str) -> List[str]:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=self.model,
            max_tokens=300,
            system=_EXTRACT_SYSTEM.format(brand=brand),
            messages=[{"role": "user", "content": (response_text or "")[:4000]}],
        )
        text = "".join(
            getattr(b, "text", "") for b in resp.content or [] if getattr(b, "type", "") == "text"
        )
        return _parse_names(text, brand)


def _parse_names(raw: Optional[str], brand: str) -> List[str]:
    """Parse a JSON array (or {"...": [...]}) of names from an LLM reply."""
    if not raw:
        return []
    raw = raw.strip()
    # Strip code fences if present.
    if raw.startswith("```"):
        raw = raw.strip("`")
        raw = raw.split("\n", 1)[-1] if "\n" in raw else raw
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    names: List[str] = []
    if isinstance(data, list):
        names = data
    elif isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                names = v
                break
    out = []
    for n in names:
        if isinstance(n, str) and n.strip() and n.strip().casefold() != brand.strip().casefold():
            out.append(n.strip())
    return _dedupe(out)


# --------------------------------------------------------------------------- #
# Config-gated construction
# --------------------------------------------------------------------------- #


def build_engines(
    *,
    openai_key: str = "",
    perplexity_key: str = "",
    gemini_key: str = "",
    claude_key: str = "",
    openai_model: str = "gpt-4o",
    perplexity_model: str = "sonar",
    gemini_model: str = "gemini-flash-latest",
    claude_model: str = "claude-haiku-4-5",
    enable_claude: bool = False,
) -> list:
    """Build the engine list from whichever keys are set (config-gated).

    Claude is off unless ``enable_claude`` is set (in addition to its key) —
    it has a lower consumer-search footprint, so it's opt-in for visibility."""
    engines = []
    if openai_key:
        engines.append(OpenAIEngine(openai_key, openai_model))
    if perplexity_key:
        engines.append(PerplexityEngine(perplexity_key, perplexity_model))
    if gemini_key:
        engines.append(GeminiEngine(gemini_key, gemini_model))
    if claude_key and enable_claude:
        engines.append(ClaudeEngine(claude_key, claude_model))
    return engines


def build_extractor(*, openai_key: str = "", anthropic_key: str = ""):
    """Pick a competitor extractor from available keys (OpenAI preferred), or None."""
    if openai_key:
        return OpenAICompetitorExtractor(openai_key)
    if anthropic_key:
        return AnthropicCompetitorExtractor(anthropic_key)
    return None
