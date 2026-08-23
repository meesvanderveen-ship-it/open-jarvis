from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional


@dataclass
class FeaturePack:
    ticker: str
    generated_at: str
    market: Dict[str, Any]
    indicators: Dict[str, Any]
    structure: Dict[str, Any]
    sentiment: Dict[str, Any]
    risk_context: Dict[str, Any]
    evidence: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AnalystReport:
    name: str
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "payload": self.payload}


@dataclass
class JudgeDecision:
    decision: str
    ticker: str
    side: str
    strategy: str
    confidence: float
    size_quote: str
    reasons: List[str]
    must_reject_if: List[str]
    raw: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
