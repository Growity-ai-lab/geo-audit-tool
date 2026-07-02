"""GEO/AIO Audit Tool.

A CLI tool that audits a URL for Generative Engine Optimization (GEO) and
AI Optimization (AIO) readiness, producing a 0-100 score and categorized
findings with actionable recommendations.
"""

from dataclasses import dataclass, field
from typing import List, Optional

__version__ = "0.1.0"

# Severity levels used for findings.
OK = "ok"
WARN = "warn"
FAIL = "fail"


@dataclass
class Finding:
    """A single observation about the audited page."""

    severity: str  # OK | WARN | FAIL
    message: str
    recommendation: str = ""
    # Set only on findings where automated detection was inconclusive (a WAF/
    # rate-limit blocked verification rather than confirming absence). Lets
    # the web layer offer a manual "I checked, it's actually X" override,
    # keyed by this string (see geo_audit/overrides.py for the known keys).
    override_key: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict) -> "Finding":
        return cls(
            severity=data["severity"],
            message=data["message"],
            recommendation=data.get("recommendation", ""),
            override_key=data.get("override_key"),
        )


@dataclass
class CategoryResult:
    """Scored result for one audit category."""

    key: str
    name: str
    score: float          # points earned (0 .. max_score)
    max_score: float      # maximum points for this category
    findings: List[Finding] = field(default_factory=list)
    # Optional raw metrics for this category (e.g. real Core Web Vitals:
    # lcp_ms, cls, inp_ms, perf_score). Empty for categories without them.
    metrics: dict = field(default_factory=dict)

    @property
    def ratio(self) -> float:
        if self.max_score == 0:
            return 0.0
        return self.score / self.max_score

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "score": round(self.score, 2),
            "max_score": self.max_score,
            "ratio": round(self.ratio, 4),
            "metrics": self.metrics,
            "findings": [
                {
                    "severity": f.severity,
                    "message": f.message,
                    "recommendation": f.recommendation,
                    "override_key": f.override_key,
                }
                for f in self.findings
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CategoryResult":
        return cls(
            key=data["key"],
            name=data["name"],
            score=data["score"],
            max_score=data["max_score"],
            findings=[Finding.from_dict(f) for f in data.get("findings", [])],
            metrics=data.get("metrics") or {},
        )
