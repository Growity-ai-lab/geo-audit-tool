"""GEO/AIO Audit Tool.

A CLI tool that audits a URL for Generative Engine Optimization (GEO) and
AI Optimization (AIO) readiness, producing a 0-100 score and categorized
findings with actionable recommendations.
"""

from dataclasses import dataclass, field
from typing import List

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


@dataclass
class CategoryResult:
    """Scored result for one audit category."""

    key: str
    name: str
    score: float          # points earned (0 .. max_score)
    max_score: float      # maximum points for this category
    findings: List[Finding] = field(default_factory=list)

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
            "findings": [
                {
                    "severity": f.severity,
                    "message": f.message,
                    "recommendation": f.recommendation,
                }
                for f in self.findings
            ],
        }
