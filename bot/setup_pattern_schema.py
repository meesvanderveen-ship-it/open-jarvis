from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List


@dataclass(frozen=True)
class SetupPatternSpec:
    setup_pattern: str
    currently_supported: bool
    detected_by: str
    used_by_agent: str
    can_create_trade_plan: bool
    can_create_future_watch: bool
    has_invalidation_level: bool
    has_trigger_level: bool
    has_entry_zone: bool
    has_stop_logic: bool
    has_target_logic: bool
    has_tests: bool
    missing: List[str]
    recommended_action: str
    priority: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


REQUIRED_SETUP_PATTERNS = [
    "trend_continuation",
    "reclaim_reversal",
    "mean_reversion",
    "breakout",
    "breakout_retest",
    "reclaim_retest",
    "pullback",
    "liquidity_sweep",
    "range_break",
    "failed_breakout",
    "support_bounce",
    "resistance_rejection",
    "vwap_reclaim",
    "ema_pullback",
    "rsi_divergence",
    "volume_expansion",
    "volatility_squeeze",
    "atr_expansion",
    "orderbook_imbalance",
    "spread_depth_opportunity",
    "momentum_continuation",
    "higher_timeframe_confluence",
]


__all__ = ["REQUIRED_SETUP_PATTERNS", "SetupPatternSpec"]
