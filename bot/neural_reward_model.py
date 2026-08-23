from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.atomic_io import atomic_write_json


DEFAULT_REWARD_SUMMARY_PATH = Path("reports/live_learning/neural-reward-summary-latest.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "filled"}


def _clamp(value: Decimal, low: Decimal = Decimal("-1.0"), high: Decimal = Decimal("1.0")) -> Decimal:
    return max(low, min(high, value))


@dataclass(frozen=True)
class RewardResult:
    reward: float
    reward_reasons: List[str]
    label: str

    def to_dict(self) -> Dict[str, Any]:
        return {"reward": self.reward, "reward_reasons": self.reward_reasons, "label": self.label}


def calculate_neural_reward(sample: Dict[str, Any], *, fee_pct: Decimal = Decimal("0.0080"), slippage_pct: Decimal = Decimal("0.0010")) -> RewardResult:
    """Deterministic, cost-aware reward for a decision/outcome sample."""
    outcome = sample.get("outcome") if isinstance(sample.get("outcome"), dict) else {}
    features = sample.get("features") if isinstance(sample.get("features"), dict) else {}
    action = str(sample.get("action_taken") or "").strip().lower()
    candidate = str(sample.get("action_candidate") or "").strip().lower()

    filled = _as_bool(outcome.get("filled"))
    missed = _as_bool(outcome.get("missed_opportunity"))
    adverse = _as_bool(outcome.get("adverse_move"))
    stop_breach = _as_bool(outcome.get("stop_breach") or outcome.get("stop_breached"))
    realized = outcome.get("realized_pnl_pct")
    realized_pct = _as_decimal(realized, "0") if realized is not None else None
    max_fav = _as_decimal(outcome.get("max_favorable_move_pct"), "0")
    max_adv = _as_decimal(outcome.get("max_adverse_move_pct"), "0")
    spread = abs(_as_decimal(features.get("spread_pct"), "0"))
    edge = _as_decimal(features.get("d2_net_edge_pct") or features.get("expected_net_edge_pct"), "0")
    reward_to_risk = _as_decimal(features.get("reward_to_risk") or features.get("d2_reward_to_risk"), "0")
    reward_to_fee = _as_decimal(features.get("reward_to_fee") or features.get("d2_reward_to_fee"), "0")
    total_cost = fee_pct + slippage_pct + (spread / Decimal("2"))

    reasons: List[str] = []
    reward = Decimal("0.0")
    label = "neutral"

    if filled:
        net = (realized_pct if realized_pct is not None else Decimal("0")) - total_cost
        if stop_breach or adverse or max_adv >= Decimal("0.020"):
            reward = Decimal("-1.00")
            label = "adverse_after_entry"
            reasons.append("stop_breach_or_clear_adverse_move_after_entry")
        elif net > Decimal("0"):
            reward = Decimal("1.00")
            label = "profitable_fill_after_costs"
            reasons.append("filled_trade_profitable_after_fees")
        elif net > Decimal("-0.005"):
            reward = Decimal("0.10")
            label = "flat_fill_after_costs"
            reasons.append("filled_trade_near_flat_after_costs")
        else:
            reward = Decimal("-0.75")
            label = "unprofitable_fill_after_costs"
            reasons.append("filled_trade_unprofitable_after_fees")
    elif action in {"wait", "watch", "skip", "analyze", "no_trade", "prefer_no_trade"}:
        if missed or max_fav >= Decimal("0.020"):
            reward = Decimal("-0.50")
            label = "missed_opportunity"
            reasons.append("missed_opportunity_after_wait_or_watch")
        elif adverse or max_adv >= Decimal("0.015"):
            reward = Decimal("0.50")
            label = "correct_wait_avoided_adverse"
            reasons.append("correct_no_trade_avoided_adverse_move")
        elif candidate in {"place_limit_buy", "prefer_limit_buy"} and max_fav >= total_cost + Decimal("0.004"):
            reward = Decimal("-0.25")
            label = "safe_entry_zone_no_fill"
            reasons.append("no_fill_while_entry_zone_would_have_filled_safely")
        else:
            reward = Decimal("0.25")
            label = "correct_wait_no_trigger"
            reasons.append("wait_near_unclear_structure_no_missed_move")
    else:
        if adverse or max_adv >= Decimal("0.020"):
            reward = Decimal("-0.75")
            label = "chase_then_adverse"
            reasons.append("chase_or_entry_candidate_followed_by_adverse_move")
        elif missed:
            reward = Decimal("-0.25")
            label = "weak_nonfill_missed"
            reasons.append("non_wait_action_without_fill_and_missed_move")
        else:
            reward = Decimal("0.0")
            reasons.append("insufficient_outcome_evidence")

    if edge and edge < total_cost:
        reward -= Decimal("0.10")
        reasons.append("expected_net_edge_below_cost")
    if reward_to_risk and reward_to_risk < Decimal("1.0"):
        reward -= Decimal("0.10")
        reasons.append("reward_to_risk_below_one")
    if reward_to_fee and reward_to_fee < Decimal("1.0"):
        reward -= Decimal("0.10")
        reasons.append("reward_to_fee_below_one")
    if spread > Decimal("0.0060") and reward < Decimal("0.50"):
        reward -= Decimal("0.05")
        reasons.append("wide_spread_cost_penalty")

    reward = _clamp(reward)
    return RewardResult(reward=float(reward), reward_reasons=reasons, label=label)


def summarize_rewards(rows: Iterable[Dict[str, Any]], *, output_path: str | Path = DEFAULT_REWARD_SUMMARY_PATH) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    total = Decimal("0")
    n = 0
    for row in rows:
        result = calculate_neural_reward(row)
        counts[result.label] = counts.get(result.label, 0) + 1
        total += _as_decimal(result.reward)
        n += 1
    report = {
        "phase": "neural_reward_model_v1",
        "generated_at": _now_iso(),
        "sample_count": n,
        "average_reward": float(total / Decimal(n)) if n else 0.0,
        "label_counts": counts,
        "read_only": True,
        "coinbase_call_attempted": False,
        "llm_call_attempted": False,
    }
    atomic_write_json(output_path, report)
    return report


__all__ = ["DEFAULT_REWARD_SUMMARY_PATH", "RewardResult", "calculate_neural_reward", "summarize_rewards"]
