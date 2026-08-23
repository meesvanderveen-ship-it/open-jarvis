from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, Optional

ZERO = Decimal("0")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_positive(items: Iterable[tuple[str, Any]]) -> tuple[str, Decimal]:
    for source, value in items:
        dec = _to_decimal(value, "0")
        if dec > ZERO:
            return source, dec
    return "", ZERO


def _bool_cfg(cfg: Any, name: str, default: bool) -> bool:
    return bool(getattr(cfg, name, default))


def _dec_cfg(cfg: Any, name: str, default: str) -> Decimal:
    return _to_decimal(getattr(cfg, name, default), default)


def _stop_breached(position: Dict[str, Any], market_context: Dict[str, Any]) -> bool:
    texts = []
    for key in ("decision", "risk_state", "status", "reason", "last_heartbeat_reason"):
        texts.append(str(market_context.get(key) or ""))
        texts.append(str(position.get(key) or ""))
    texts.extend(str(x) for x in market_context.get("reasons") or [])
    return any("stop_breached_or_below_invalidation" in t or "close_position" in t for t in texts)


def build_exit_target_source_policy_report(
    *,
    cfg: Any,
    position: Dict[str, Any],
    market_context: Optional[Dict[str, Any]] = None,
    trade_plan: Optional[Dict[str, Any]] = None,
    current_mid: Any = None,
    risk_reward_fallback_target: Any = None,
) -> Dict[str, Any]:
    market = _as_dict(market_context)
    plan = _as_dict(trade_plan)
    entry = _to_decimal(position.get("entry_price") or position.get("avg_entry_price"), "0")
    mid = _to_decimal(current_mid or market.get("current_mid") or market.get("mid_price") or market.get("current_price"), "0")
    nearest_resistance = _to_decimal(
        market.get("nearest_resistance")
        or market.get("resistance_level")
        or _as_dict(market.get("market_structure")).get("resistance_level"),
        "0",
    )
    nearest_support = _to_decimal(
        market.get("nearest_support")
        or market.get("support_level")
        or _as_dict(market.get("market_structure")).get("support_level"),
        "0",
    )
    stopped = _stop_breached(position, market)
    max_distance = _dec_cfg(cfg, "exit_target_max_distance_from_mid_pct", "0.0350")
    allow_far_with_resistance = _bool_cfg(cfg, "exit_target_allow_far_tp_with_resistance_confirmation", True)
    stale_if_stop_breached = _bool_cfg(cfg, "exit_target_stale_if_stop_breached", True)
    require_fresh_when_stopped = _bool_cfg(cfg, "exit_target_require_fresh_context_when_stop_breached", True)

    source, target = _first_positive(
        [
            ("gpt_market_context_exit_target", market.get("exit_target") or market.get("tp1_price") or market.get("take_profit_1")),
            ("indicator_resistance_target", nearest_resistance),
            ("trade_plan_target", plan.get("take_profit_1") or plan.get("target_price") or plan.get("take_profit_price")),
            ("position_take_profit_1", position.get("take_profit_1")),
            ("position_take_profit_price", position.get("take_profit_price")),
            ("risk_reward_default_target", risk_reward_fallback_target),
        ]
    )
    used_market_context = source in {"gpt_market_context_exit_target", "indicator_resistance_target"}
    used_position_fallback = source.startswith("position_")
    used_risk_reward_fallback = source == "risk_reward_default_target"
    distance_mid = ((target - mid) / mid) if target > ZERO and mid > ZERO else ZERO
    distance_entry = ((target - entry) / entry) if target > ZERO and entry > ZERO else ZERO
    resistance_confirmed = bool(
        nearest_resistance > ZERO
        and target > ZERO
        and abs(target - nearest_resistance) / nearest_resistance <= Decimal("0.0100")
    )
    far = bool(distance_mid.copy_abs() > max_distance) if mid > ZERO and target > ZERO else False
    stale = False
    reason = source or "target_missing"
    strategy_class = "take_profit"
    if stopped:
        strategy_class = "stop_or_risk_exit"
        if stale_if_stop_breached and target > mid > ZERO:
            stale = True
            reason = "stale_exit_above_market"
        if require_fresh_when_stopped and not used_market_context:
            stale = True
            reason = "stop_breached_requires_fresh_context"
    elif far and not (allow_far_with_resistance and resistance_confirmed):
        stale = True
        reason = "target_far_from_mid_without_resistance_confirmation"
    if source == "risk_reward_default_target":
        reason = "stored_risk_reward_default_target" if not stale else reason

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_price": str(target),
        "target_source": source or "none",
        "target_reason": reason,
        "target_strategy_class": strategy_class,
        "is_take_profit_target": bool(target > ZERO and not stopped),
        "is_stop_or_risk_exit": bool(stopped),
        "is_stale_target": bool(stale),
        "distance_from_current_mid_pct": str(distance_mid),
        "distance_from_entry_pct": str(distance_entry),
        "nearest_resistance": str(nearest_resistance),
        "nearest_support": str(nearest_support),
        "indicator_context_available": bool(nearest_resistance > ZERO or nearest_support > ZERO),
        "used_market_context": used_market_context,
        "used_position_fallback": used_position_fallback,
        "used_risk_reward_fallback": used_risk_reward_fallback,
        "stop_breach_detected": bool(stopped),
        "resistance_confirmation": resistance_confirmed,
        "max_distance_from_mid_pct": str(max_distance),
    }


__all__ = ["build_exit_target_source_policy_report"]
