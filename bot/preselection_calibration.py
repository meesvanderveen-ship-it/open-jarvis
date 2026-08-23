from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Tuple


def _score(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _dec(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def evaluate_final_judge_escalation(
    judge_input: Dict[str, Any],
    *,
    min_trade_quote: Decimal = Decimal("20.00"),
    max_spread_pct: Decimal = Decimal("0.0060"),
    min_gate_confidence: int = 62,
    min_synth_confidence: int = 60,
    min_bull_score: int = 56,
    max_bear_score: int = 72,
) -> Tuple[bool, Dict[str, Any]]:
    feature_pack = judge_input.get("feature_pack", {}) or {}
    market = feature_pack.get("market", {}) or {}
    risk_context = feature_pack.get("risk_context", {}) or {}
    entry_gate = feature_pack.get("entry_gate", {}) or {}
    synth = judge_input.get("synth", {}) or {}
    bull = judge_input.get("bull", {}) or {}
    bear = judge_input.get("bear", {}) or {}
    breakout = judge_input.get("breakout", {}) or {}
    trend = judge_input.get("trend", {}) or {}
    meanrev = judge_input.get("meanrev", {}) or {}

    decision = str(entry_gate.get("decision") or "").lower()
    priority = str(entry_gate.get("priority") or "normal").lower()
    gate_conf = _score(entry_gate.get("confidence"))
    synth_conf = _score(synth.get("composite_confidence"))
    bull_score = _score(bull.get("bull_case_score"))
    bear_score = _score(bear.get("bear_case_score"))
    breakout_quality = _score(breakout.get("breakout_quality_score"))
    breakout_confirmation = _score(breakout.get("breakout_confirmation_score"))
    trend_strength = _score(trend.get("trend_strength_score"))
    trend_alignment = _score(trend.get("trend_alignment_score"))

    metrics: Dict[str, Any] = {
        "liquidity_quality": 0,
        "invalidation_quality": 0,
        "entry_zone_quality": 0,
        "trigger_freshness": 0,
        "setup_potential": 0,
        "risk_defined_bonus": 0,
        "hard_blocker_penalty": 0,
        "stale_data_penalty": 0,
        "chase_penalty": 0,
        "escalation_score": 0,
        "escalate_to_final_judge": False,
        "warnings": [],
    }

    if decision not in {"analyze", "priority_analyze", "watch"}:
        metrics["top_blocker"] = f"entry_gate_decision_not_judge_worthy:{decision or 'missing'}"
        metrics["hard_blocker_penalty"] = 100
        return False, metrics
    if market.get("trading_disabled") is True or market.get("cancel_only") is True:
        metrics["top_blocker"] = "market_not_tradeable"
        metrics["hard_blocker_penalty"] = 100
        return False, metrics
    spread = _dec(market.get("spread_pct"), "1")
    max_spread = _dec(market.get("max_spread_pct"), str(max_spread_pct))
    if spread > max_spread:
        metrics["top_blocker"] = "spread_too_wide_for_expensive_judge"
        metrics["hard_blocker_penalty"] = 100
        return False, metrics
    if _dec(risk_context.get("available_quote_balance"), "0") < min_trade_quote:
        metrics["top_blocker"] = "available_quote_below_min_trade"
        metrics["hard_blocker_penalty"] = 100
        return False, metrics

    metrics["liquidity_quality"] = 25 if spread <= max_spread * Decimal("0.50") else 15
    invalidation_present = bool(
        str(synth.get("invalidation") or "").strip()
        or str(breakout.get("breakout_invalidation_level") or "").strip()
        or str(trend.get("trend_stop_logic") or "").strip()
        or str(meanrev.get("meanrev_stop_logic") or "").strip()
    )
    if not invalidation_present:
        metrics["top_blocker"] = "defined_invalidation_missing_for_final_judge_escalation"
        metrics["hard_blocker_penalty"] = 100
        return False, metrics
    metrics["invalidation_quality"] = 22
    metrics["risk_defined_bonus"] = 12
    entry_zone_present = any(str(v or "").strip() for v in (trend.get("entry_zone_low"), trend.get("entry_zone_high"), meanrev.get("entry_zone_low"), meanrev.get("entry_zone_high"), breakout.get("breakout_trigger_level")))
    metrics["entry_zone_quality"] = 18 if entry_zone_present else 0
    metrics["trigger_freshness"] = 15 if str(synth.get("key_trigger") or breakout.get("breakout_trigger_level") or "").strip() else 5

    local_bonus = 0
    if priority == "high":
        local_bonus += 14
    if decision in {"analyze", "priority_analyze"}:
        local_bonus += 12
    if breakout_quality >= 55 or breakout_confirmation >= 45:
        local_bonus += 10
    if trend_strength >= 50 or trend_alignment >= 50:
        local_bonus += 8
    metrics["setup_potential"] = max(0, min(30, local_bonus + max(0, bull_score - 45) // 2 + max(0, synth_conf - 50) // 2))
    bearish_penalty = 10 if bear_score > max_bear_score and bear_score >= bull_score else 0
    confidence_penalty = 0
    if gate_conf < min_gate_confidence and priority != "high":
        confidence_penalty += min(12, min_gate_confidence - gate_conf)
    if synth_conf < min_synth_confidence:
        confidence_penalty += min(12, min_synth_confidence - synth_conf)
    if bull_score < min_bull_score:
        confidence_penalty += min(10, min_bull_score - bull_score)
    if bear_score >= bull_score:
        metrics["warnings"].append("bear_score_dominant_warning")
    metrics["escalation_score"] = int(
        metrics["liquidity_quality"]
        + metrics["invalidation_quality"]
        + metrics["entry_zone_quality"]
        + metrics["trigger_freshness"]
        + metrics["setup_potential"]
        + metrics["risk_defined_bonus"]
        - bearish_penalty
        - confidence_penalty
    )
    min_escalation = 68 if decision == "watch" else 58
    metrics["escalate_to_final_judge"] = metrics["escalation_score"] >= min_escalation
    if not metrics["escalate_to_final_judge"]:
        metrics["top_blocker"] = f"escalation_score_below_threshold:{metrics['escalation_score']}<{min_escalation}"
    return bool(metrics["escalate_to_final_judge"]), metrics

