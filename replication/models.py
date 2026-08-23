from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ReplicationEnvelope:
    event_id: str
    timestamp: str
    source_bot: str
    ticker: str
    decision: str
    side: str
    strategy: Optional[str] = None
    setup_type: Optional[str] = None
    confidence: int = 0
    requested_size_quote: float = 0.0
    requested_size_base: float = 0.0
    reason_summary: List[str] = field(default_factory=list)
    must_reject_if: List[str] = field(default_factory=list)
    analysis: Dict[str, Any] = field(default_factory=dict)
    entry_gate: Dict[str, Any] = field(default_factory=dict)
    risk_context: Dict[str, Any] = field(default_factory=dict)
    position_context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "source_bot": self.source_bot,
            "ticker": self.ticker,
            "decision": self.decision,
            "side": self.side,
            "strategy": self.strategy,
            "setup_type": self.setup_type,
            "confidence": self.confidence,
            "requested_size_quote": self.requested_size_quote,
            "requested_size_base": self.requested_size_base,
            "reason_summary": self.reason_summary,
            "must_reject_if": self.must_reject_if,
            "analysis": self.analysis,
            "entry_gate": self.entry_gate,
            "risk_context": self.risk_context,
            "position_context": self.position_context,
            "metadata": self.metadata,
        }