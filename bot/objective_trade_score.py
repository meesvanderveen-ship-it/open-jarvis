from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Tuple


def _d(value: Any, default: str = "0") -> Decimal:
    try:
        if value in (None, ""):
            return Decimal(default)
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _nested(mapping: Dict[str, Any], *keys: str) -> Any:
    cur: Any = mapping
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _component(name: str, score: float, reason: str) -> Dict[str, Any]:
    return {"score": max(0.0, min(1.0, float(score))), "reason": reason}


def grade_for_score(score: float) -> str:
    if score >= 0.78:
        return "A"
    if score >= 0.62:
        return "B"
    if score >= 0.46:
        return "C"
    if score >= 0.30:
        return "D"
    return "F"


def score_trade_context(context: Dict[str, Any]) -> Dict[str, Any]:
    analysis = context if isinstance(context, dict) else {}
    feature_pack = analysis.get("feature_pack") if isinstance(analysis.get("feature_pack"), dict) else analysis
    judge = analysis.get("judge") if isinstance(analysis.get("judge"), dict) else {}
    plan = analysis.get("trade_plan") if isinstance(analysis.get("trade_plan"), dict) else {}
    market = feature_pack.get("market") if isinstance(feature_pack.get("market"), dict) else {}
    indicators = feature_pack.get("indicators") if isinstance(feature_pack.get("indicators"), dict) else {}
    structure = feature_pack.get("structure") if isinstance(feature_pack.get("structure"), dict) else {}
    micro = feature_pack.get("microstructure") if isinstance(feature_pack.get("microstructure"), dict) else {}
    orderbook = feature_pack.get("orderbook_context") if isinstance(feature_pack.get("orderbook_context"), dict) else {}
    rules = feature_pack.get("product_rules") or feature_pack.get("exchange_rules") or {}
    rules = rules if isinstance(rules, dict) else {}

    entry = _d(plan.get("preferred_limit_price") or plan.get("entry_zone_low") or judge.get("preferred_limit_price") or market.get("mid_price"))
    stop = _d(plan.get("stop_loss") or plan.get("invalidation_price") or judge.get("invalidation_price"))
    target = _d(plan.get("take_profit_1") or judge.get("target_price_1"))
    spread = _d(market.get("spread_pct") or orderbook.get("spread_pct"), "1")
    fee = _d(_nested(feature_pack, "risk_context", "roundtrip_fee_pct"), "0.012")
    vol_1h = _d(_nested(micro, "1h", "volume_vs_avg"), "0")
    adx_4h = _d(_nested(indicators, "4h", "adx_14"), "0")
    rsi_1h = _d(_nested(indicators, "1h", "rsi_14"), "50")

    hard_blockers: List[str] = []
    soft_warnings: List[str] = []
    if entry <= 0:
        hard_blockers.append("entry_price_missing")
    if stop <= 0:
        hard_blockers.append("invalidation_or_stop_missing")
    if target <= 0:
        hard_blockers.append("target_missing")
    if not rules.get("base_increment") and not rules.get("base_increment_size"):
        soft_warnings.append("product_base_increment_missing_from_context")
    if not rules.get("price_increment") and not rules.get("price_increment_size"):
        soft_warnings.append("product_price_increment_missing_from_context")

    rr = Decimal("0")
    rf = Decimal("0")
    if entry > 0 and stop > 0 and target > entry and stop < entry:
        rr = (target - entry) / (entry - stop)
        rf = ((target - entry) / entry) / fee if fee > 0 else Decimal("0")
    else:
        soft_warnings.append("reward_to_risk_not_positive")

    components = {
        "trend_alignment": _component("trend_alignment", min(float(adx_4h / Decimal("35")), 1.0), f"4h_adx={adx_4h}"),
        "support_resistance_quality": _component("support_resistance_quality", 0.75 if structure.get("nearest_support") or structure.get("nearest_resistance") else 0.25, "structure levels present" if structure else "structure sparse"),
        "volume_confirmation": _component("volume_confirmation", min(float(vol_1h / Decimal("1.5")), 1.0), f"1h_volume_vs_avg={vol_1h}"),
        "volatility_regime": _component("volatility_regime", 0.65 if 35 <= float(rsi_1h) <= 70 else 0.35, f"1h_rsi={rsi_1h}"),
        "spread_depth_quality": _component("spread_depth_quality", max(0.0, 1.0 - float(spread / Decimal("0.006"))), f"spread_pct={spread}"),
        "reward_to_risk": _component("reward_to_risk", min(float(rr / Decimal("2.0")), 1.0), f"rr={rr}"),
        "reward_to_fee": _component("reward_to_fee", min(float(rf / Decimal("4.0")), 1.0), f"reward_to_fee={rf}"),
        "invalidation_clarity": _component("invalidation_clarity", 1.0 if stop > 0 else 0.0, "stop/invalidation present" if stop > 0 else "missing"),
        "product_precision_feasibility": _component("product_precision_feasibility", 1.0 if rules else 0.35, "product rules present" if rules else "product rules missing"),
    }
    weights: Dict[str, float] = {
        "trend_alignment": 0.12,
        "support_resistance_quality": 0.10,
        "volume_confirmation": 0.10,
        "volatility_regime": 0.08,
        "spread_depth_quality": 0.12,
        "reward_to_risk": 0.18,
        "reward_to_fee": 0.12,
        "invalidation_clarity": 0.10,
        "product_precision_feasibility": 0.08,
    }
    score = sum(components[k]["score"] * weights[k] for k in weights)
    if hard_blockers:
        score = min(score, 0.24)
    grade = grade_for_score(score)
    if hard_blockers:
        action = "ignore"
    elif score >= 0.70:
        action = "judge"
    elif score >= 0.50:
        action = "watch"
    elif score >= 0.38:
        action = "recheck"
    else:
        action = "ignore"
    return {
        "objective_score": round(float(score), 4),
        "grade": grade,
        "components": components,
        "hard_blockers": hard_blockers,
        "soft_warnings": soft_warnings,
        "recommended_action": action,
        "live_order_authority": False,
        "read_only": True,
    }


def audit_recent_scores(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    scored = [{"ticker": row.get("ticker"), **score_trade_context(row)} for row in rows]
    return {
        "phase": "objective_trade_score_audit_v1",
        "read_only": True,
        "live_order_authority": False,
        "rows": len(scored),
        "scores": scored,
    }


__all__ = ["audit_recent_scores", "grade_for_score", "score_trade_context"]
