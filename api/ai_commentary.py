"""AI-generated narrative commentary for audit reports (Claude).

A web-layer enrichment, not an engine module: it never affects scoring, only
adds a short executive-summary paragraph and one rationale per category on top
of an already-computed ``AuditReport``. Config-gated like PSI — runs whenever
``ANTHROPIC_API_KEY`` is set; any error (missing key, network, bad response)
degrades to ``None`` so the report renders unaffected.
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from pydantic import BaseModel

from geo_audit.scorer import AuditReport

logger = logging.getLogger("geo_audit.api")


class CategoryNote(BaseModel):
    key: str
    note: str


class Commentary(BaseModel):
    executive_summary: str
    category_notes: List[CategoryNote]


_SYSTEM_PROMPT = (
    "Sen bir GEO (Generative Engine Optimization) danışmanısın. Sana bir web "
    "sitesinin AI audit sonucu (skorlar + bulgular) JSON olarak verilecek. "
    "Türkçe, kısa ve net bir yönetici özeti (2-3 cümle) ve her kategori için "
    "1-2 cümlelik bir yorum yaz. Yorumların somut olsun: hangi bulgu neden "
    "önemli, ne anlama geliyor. Pazarlama dili veya genel tavsiye kullanma; "
    "yalnızca verilen skor ve bulgulara dayan."
)


def _report_payload(report: AuditReport) -> dict:
    return {
        "url": report.final_url,
        "geo_score": round(report.total_score, 1),
        "max_score": report.max_score,
        "grade": report.grade,
        "categories": [
            {
                "key": c.key,
                "name": c.name,
                "score": round(c.score, 1),
                "max_score": c.max_score,
                "findings": [
                    {"severity": f.severity, "message": f.message}
                    for f in c.findings
                ],
            }
            for c in report.categories
        ],
    }


def generate_commentary(
    report: AuditReport, api_key: str, model: str
) -> Optional[Commentary]:
    """Call Claude for narrative commentary, or None on any failure.

    Never raises — a missing key, network error, or malformed response should
    never break an audit; the report simply ships without commentary.
    """
    if not report.reachable or not api_key:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        payload = json.dumps(_report_payload(report), ensure_ascii=False)
        response = client.messages.parse(
            model=model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Bu audit sonucu için yönetici özeti ve kategori "
                        f"yorumları yaz:\n\n{payload}"
                    ),
                }
            ],
            output_format=Commentary,
        )
        return response.parsed_output
    except Exception:
        logger.exception("AI commentary generation failed; report unaffected")
        return None
