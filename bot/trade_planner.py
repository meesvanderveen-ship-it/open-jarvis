from __future__ import annotations

import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple


ALLOWED_PLAN_ACTIONS = {
    "no_plan",
    "prepare_buy",
    "prepare_reclaim",
    "prepare_breakout",
    "prepare_mean_reversion",
    "prepare_resting_limit_entry",
    "prepare_retest_limit_entry",
    "prepare_pullback_limit_entry",
    "prepare_reclaim_retest_limit_entry",
    "prepare_breakout_retest_limit_entry",
    "manage_existing",
    "reduce",
    "close",
}

ALLOWED_SETUP_TYPES = {
    "trend_continuation",
    "reclaim_reversal",
    "mean_reversion",
    "breakout_retest",
    "support_sweep_reclaim",
    "failed_breakout",
    "range_trade",
    "position_management",
    "unclear",
}

ACTIONABLE_PLAN_ACTIONS = {
    "prepare_buy",
    "prepare_reclaim",
    "prepare_breakout",
    "prepare_mean_reversion",
    "prepare_resting_limit_entry",
    "prepare_retest_limit_entry",
    "prepare_pullback_limit_entry",
    "prepare_reclaim_retest_limit_entry",
    "prepare_breakout_retest_limit_entry",
    "manage_existing",
    "reduce",
    "close",
}

ENTRY_PLAN_ACTIONS = {
    "prepare_buy",
    "prepare_reclaim",
    "prepare_breakout",
    "prepare_mean_reversion",
    "prepare_resting_limit_entry",
    "prepare_retest_limit_entry",
    "prepare_pullback_limit_entry",
    "prepare_reclaim_retest_limit_entry",
    "prepare_breakout_retest_limit_entry",
}


DEFAULT_NO_PLAN: Dict[str, Any] = {
    "plan_type": "no_plan",
    "plan_action": "no_plan",
    "ticker": None,
    "side": "NONE",
    "setup_type": "unclear",
    "entry_zone_low": None,
    "entry_zone_high": None,
    "trigger_price": None,
    "trigger": "",
    "do_not_chase_above": None,
    "preferred_limit_price": None,
    "invalidation_price": None,
    "stop_loss": None,
    "stop_loss_price": None,
    "take_profit_1": None,
    "take_profit_2": None,
    "target_price_1": None,
    "target_price_2": None,
    "max_quote_size": 0.0,
    "invalidation": "",
    "max_size_quote": 0.0,
    "monitoring_rules": [],
    "risk_notes": [],
    "confidence": 0,
    "planner_confidence": 0,
    "planner_blockers": [],
    "must_not_trade_if": [],
    "why_plan_is_valid": "",
    "why_size_is_small": "",
    "reason": "No valid trade plan.",
    "no_plan_reason": "No valid trade plan.",
    "missing_fields": [],
    "hard_blockers": [],
    "soft_warnings": [],
    "would_be_starter_probe_if_relaxed": False,
    "source": "default_no_plan",
    "plan_status": "inactive",
    "pattern_alignment": "neutral",
    "entry_reason": "",
    "why_not_market_order": "",
    "why_resting_limit_is_or_is_not_valid": "",
    "setup_expiry_minutes": None,
}


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if d.is_nan() or d.is_infinite():
        return None
    return d


def _to_float_or_none(value: Any) -> Optional[float]:
    d = _to_decimal(value)
    if d is None:
        return None
    return float(d)


def _to_quote_float(value: Any) -> float:
    d = _to_decimal(value)
    if d is None or d < 0:
        return 0.0
    return float(d)


def _to_confidence(value: Any) -> int:
    d = _to_decimal(value)
    if d is None:
        return 0
    if d <= 1:
        d = d * Decimal("100")
    try:
        confidence = int(round(float(d)))
    except Exception:
        confidence = 0
    return max(0, min(100, confidence))


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, (dict, bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def build_default_no_plan(
    ticker: Optional[str] = None,
    reason: str = "No valid trade plan.",
    source: str = "default_no_plan",
    *,
    missing_fields: Optional[List[str]] = None,
    hard_blockers: Optional[List[str]] = None,
    soft_warnings: Optional[List[str]] = None,
    would_be_starter_probe_if_relaxed: bool = False,
) -> Dict[str, Any]:
    plan = deepcopy(DEFAULT_NO_PLAN)
    plan["ticker"] = ticker
    plan["reason"] = reason
    plan["no_plan_reason"] = reason
    plan["missing_fields"] = list(missing_fields or [])
    plan["hard_blockers"] = list(hard_blockers or [])
    plan["planner_blockers"] = list(hard_blockers or [])
    plan["soft_warnings"] = list(soft_warnings or [])
    plan["would_be_starter_probe_if_relaxed"] = bool(would_be_starter_probe_if_relaxed)
    plan["source"] = source
    return plan


def _first_decimal(*values: Any) -> Optional[Decimal]:
    for value in values:
        d = _to_decimal(value)
        if d is not None and d > 0:
            return d
    return None


def _nested(mapping: Dict[str, Any], *keys: str) -> Any:
    cur: Any = mapping
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _extract_price_from_text(value: Any) -> Optional[Decimal]:
    d = _to_decimal(value)
    if d is not None and d > 0:
        return d
    text = str(value or "")
    for match in re.findall(r"\d+(?:\.\d+)?", text):
        d = _to_decimal(match)
        if d is not None and d > 0:
            return d
    return None


def _extract_current_price(feature_pack: Dict[str, Any]) -> Optional[Decimal]:
    market = feature_pack.get("market") if isinstance(feature_pack.get("market"), dict) else {}
    orderbook = feature_pack.get("orderbook_context") if isinstance(feature_pack.get("orderbook_context"), dict) else {}
    orderbook_summary = feature_pack.get("orderbook_summary") if isinstance(feature_pack.get("orderbook_summary"), dict) else {}
    indicators = feature_pack.get("indicators") if isinstance(feature_pack.get("indicators"), dict) else {}
    raw_context = feature_pack.get("raw_context") if isinstance(feature_pack.get("raw_context"), dict) else {}
    return _first_decimal(
        feature_pack.get("current_price"),
        feature_pack.get("price"),
        feature_pack.get("last_price"),
        feature_pack.get("mid_price"),
        market.get("current_price"),
        market.get("last_price"),
        market.get("mid_price"),
        orderbook.get("mid_price"),
        orderbook_summary.get("mid_price"),
        _nested(indicators, "1h", "close"),
        _nested(indicators, "4h", "close"),
        _nested(raw_context, "1h", "latest_close"),
        _nested(raw_context, "4h", "latest_close"),
    )


def _extract_spread(feature_pack: Dict[str, Any]) -> Optional[Decimal]:
    market = feature_pack.get("market") if isinstance(feature_pack.get("market"), dict) else {}
    orderbook = feature_pack.get("orderbook_context") if isinstance(feature_pack.get("orderbook_context"), dict) else {}
    orderbook_summary = feature_pack.get("orderbook_summary") if isinstance(feature_pack.get("orderbook_summary"), dict) else {}
    return _first_decimal(market.get("spread_pct"), orderbook.get("spread_pct"), orderbook_summary.get("spread_pct"), feature_pack.get("spread_pct"))


def _market_snapshot_stale(feature_pack: Dict[str, Any]) -> bool:
    market = feature_pack.get("market") if isinstance(feature_pack.get("market"), dict) else {}
    orderbook = feature_pack.get("orderbook_context") if isinstance(feature_pack.get("orderbook_context"), dict) else {}
    orderbook_summary = feature_pack.get("orderbook_summary") if isinstance(feature_pack.get("orderbook_summary"), dict) else {}
    values = [feature_pack, market, orderbook, orderbook_summary]
    for item in values:
        if item.get("stale") is True or item.get("market_snapshot_stale") is True:
            return True
        if str(item.get("freshness_status") or "").strip().lower() == "stale":
            return True
        if item.get("snapshot_available") is False:
            return True
    return False


def _has_no_liquidity(feature_pack: Dict[str, Any]) -> bool:
    market = feature_pack.get("market") if isinstance(feature_pack.get("market"), dict) else {}
    orderbook = feature_pack.get("orderbook_context") if isinstance(feature_pack.get("orderbook_context"), dict) else {}
    orderbook_summary = feature_pack.get("orderbook_summary") if isinstance(feature_pack.get("orderbook_summary"), dict) else {}
    score = _to_decimal(market.get("liquidity_score") or orderbook.get("liquidity_score") or orderbook_summary.get("liquidity_score"))
    if score is not None and score <= 0:
        return True
    bid = _first_decimal(market.get("best_bid"), orderbook.get("best_bid"), orderbook_summary.get("best_bid"))
    ask = _first_decimal(market.get("best_ask"), orderbook.get("best_ask"), orderbook_summary.get("best_ask"))
    if (bid is not None and bid <= 0) or (ask is not None and ask <= 0):
        return True
    bid_size = _to_decimal(market.get("best_bid_size") or orderbook.get("best_bid_size") or orderbook_summary.get("best_bid_size"))
    ask_size = _to_decimal(market.get("best_ask_size") or orderbook.get("best_ask_size") or orderbook_summary.get("best_ask_size"))
    return bool((bid_size is not None and bid_size <= 0) or (ask_size is not None and ask_size <= 0))


def _extract_entry_zone(planner_input: Dict[str, Any], current: Decimal) -> Tuple[Optional[Decimal], Optional[Decimal], str]:
    trend = planner_input.get("trend") if isinstance(planner_input.get("trend"), dict) else {}
    meanrev = planner_input.get("meanrev") if isinstance(planner_input.get("meanrev"), dict) else {}
    breakout = planner_input.get("breakout") if isinstance(planner_input.get("breakout"), dict) else {}
    chart = planner_input.get("chart_patterns") if isinstance(planner_input.get("chart_patterns"), dict) else {}
    market_structure = chart.get("market_structure") if isinstance(chart.get("market_structure"), dict) else {}
    pairs = (
        (trend.get("entry_zone_low"), trend.get("entry_zone_high"), "trend_entry_zone"),
        (meanrev.get("entry_zone_low"), meanrev.get("entry_zone_high"), "meanrev_entry_zone"),
    )
    for low_raw, high_raw, source in pairs:
        low = _to_decimal(low_raw)
        high = _to_decimal(high_raw)
        if low is not None and high is not None and low > 0 and high > 0:
            return (min(low, high), max(low, high), source)
    trigger = _extract_price_from_text(breakout.get("breakout_trigger_level"))
    if trigger is not None:
        return (trigger * Decimal("0.9975"), trigger * Decimal("1.0025"), "breakout_trigger_level")
    support = _first_decimal(market_structure.get("nearest_support"), chart.get("nearest_support"), _nested(chart, "levels", "nearest_support"))
    if support is not None:
        return (support * Decimal("0.9975"), support * Decimal("1.0100"), "chart_support_zone")
    return (None, None, "")


def _extract_invalidation(planner_input: Dict[str, Any]) -> Tuple[Optional[Decimal], str]:
    synth = planner_input.get("synth") if isinstance(planner_input.get("synth"), dict) else {}
    trend = planner_input.get("trend") if isinstance(planner_input.get("trend"), dict) else {}
    meanrev = planner_input.get("meanrev") if isinstance(planner_input.get("meanrev"), dict) else {}
    breakout = planner_input.get("breakout") if isinstance(planner_input.get("breakout"), dict) else {}
    for value, source in (
        (synth.get("invalidation"), "synth_invalidation"),
        (breakout.get("breakout_invalidation_level"), "breakout_invalidation_level"),
        (trend.get("trend_stop_logic"), "trend_stop_logic"),
        (meanrev.get("meanrev_stop_logic"), "meanrev_stop_logic"),
    ):
        price = _extract_price_from_text(value)
        if price is not None:
            return price, source
    return None, ""


def _soft_warnings(planner_input: Dict[str, Any]) -> List[str]:
    warnings: List[str] = []
    bull = planner_input.get("bull") if isinstance(planner_input.get("bull"), dict) else {}
    bear = planner_input.get("bear") if isinstance(planner_input.get("bear"), dict) else {}
    synth = planner_input.get("synth") if isinstance(planner_input.get("synth"), dict) else {}
    feature_pack = planner_input.get("feature_pack") if isinstance(planner_input.get("feature_pack"), dict) else {}
    decision_context = feature_pack.get("decision_context") if isinstance(feature_pack.get("decision_context"), dict) else {}
    shadow = decision_context.get("neural_shadow_policy") if isinstance(decision_context.get("neural_shadow_policy"), dict) else {}
    bull_score = _to_decimal(bull.get("bull_case_score")) or Decimal("0")
    bear_score = _to_decimal(bear.get("bear_case_score")) or Decimal("0")
    synth_conf = _to_decimal(synth.get("composite_confidence")) or Decimal("0")
    if bear_score >= bull_score and bear_score > 0:
        warnings.append("bear_score_dominant_soft_warning")
    if bull_score < Decimal("56"):
        warnings.append("bull_score_below_standard_threshold_soft_warning")
    if synth_conf < Decimal("60"):
        warnings.append("synth_confidence_below_standard_threshold_soft_warning")
    if str(shadow.get("prediction") or "").lower() in {"prefer_no_trade", "no_trade"}:
        warnings.append("neural_shadow_prefer_no_trade_soft_warning")
    return warnings


def build_starter_probe_plan_from_context(
    planner_input: Dict[str, Any],
    *,
    ticker: str,
    max_size_quote: Any = None,
    min_size_quote: Any = None,
    source: str = "deterministic_starter_probe_fallback",
) -> Dict[str, Any]:
    feature_pack = planner_input.get("feature_pack") if isinstance(planner_input.get("feature_pack"), dict) else {}
    risk_context = feature_pack.get("risk_context") if isinstance(feature_pack.get("risk_context"), dict) else {}
    market = feature_pack.get("market") if isinstance(feature_pack.get("market"), dict) else {}
    entry_gate = feature_pack.get("entry_gate") if isinstance(feature_pack.get("entry_gate"), dict) else {}
    synth = planner_input.get("synth") if isinstance(planner_input.get("synth"), dict) else {}
    pending = planner_input.get("pending_trade_plan") if isinstance(planner_input.get("pending_trade_plan"), dict) else {}

    missing: List[str] = []
    hard: List[str] = []
    soft = _soft_warnings(planner_input)
    current = _extract_current_price(feature_pack)
    if current is None:
        missing.append("current_price")
    if _market_snapshot_stale(feature_pack):
        hard.append("stale_market_data")
    if market.get("trading_disabled") is True or market.get("cancel_only") is True:
        hard.append("market_not_tradeable")
    if risk_context.get("engine_state", {}).get("cooldown_active"):
        hard.append("cooldown_active")
    if risk_context.get("open_order_blocker") or risk_context.get("duplicate_order_blocker") or risk_context.get("position_limit_blocker"):
        hard.append("open_order_duplicate_or_position_limit_blocker")

    spread = _extract_spread(feature_pack)
    max_spread = _to_decimal(market.get("max_spread_pct")) or Decimal("0.0060")
    if spread is None:
        missing.append("spread_pct")
    elif spread > max_spread:
        hard.append(f"spread_too_wide:{spread}>{max_spread}")
    if _has_no_liquidity(feature_pack):
        hard.append("no_liquidity")

    min_quote = _to_decimal(min_size_quote) or Decimal("50.00")
    hard_cap = _to_decimal(max_size_quote) or Decimal("100.00")
    available_quote = _to_decimal(risk_context.get("available_quote_balance"))
    if available_quote is not None and available_quote < min_quote:
        hard.append(f"available_quote_below_min_trade:{available_quote}<{min_quote}")
    starter_quote = max(min_quote, Decimal("50.00"))
    starter_quote = min(starter_quote, hard_cap)
    if starter_quote < min_quote or starter_quote <= 0:
        hard.append(f"planner_max_size_below_min_trade:{starter_quote}<{min_quote}")

    if current is None:
        return build_default_no_plan(
            ticker=ticker,
            reason="starter_probe_missing_current_price",
            source=source,
            missing_fields=missing,
            hard_blockers=hard,
            soft_warnings=soft,
        )

    zone_low, zone_high, zone_source = _extract_entry_zone(planner_input, current)
    if zone_low is None or zone_high is None:
        missing.append("entry_zone")
    invalidation, invalidation_source = _extract_invalidation(planner_input)
    if invalidation is None:
        missing.append("invalidation_price")
    elif invalidation >= current:
        hard.append("breakdown_through_invalidation")
    else:
        stop_distance = (current - invalidation) / current
        if stop_distance > Decimal("0.050"):
            hard.append(f"invalidation_not_close_enough:{stop_distance:.4f}>0.0500")
        elif stop_distance <= Decimal("0.001"):
            hard.append("invalidation_too_close_to_current_price_noise")

    if zone_low is not None and zone_high is not None:
        near_zone_ceiling = zone_high * Decimal("1.0100")
        if current > near_zone_ceiling:
            hard.append(f"price_not_near_entry_or_support_zone:{current}>{near_zone_ceiling}")

    do_not_chase = None
    pending_plan = pending.get("plan") if isinstance(pending.get("plan"), dict) else {}
    pending_trade_plan = pending_plan.get("trade_plan") if isinstance(pending_plan.get("trade_plan"), dict) else {}
    explicit_do_not_chase = _first_decimal(
        pending.get("do_not_chase_above"),
        pending_trade_plan.get("do_not_chase_above"),
        planner_input.get("do_not_chase_above"),
    )
    if explicit_do_not_chase is not None and current > explicit_do_not_chase:
        hard.append("do_not_chase_hard_violation")
    if zone_high is not None:
        do_not_chase = max(zone_high * Decimal("1.0060"), current * Decimal("1.0020"))
    elif current is not None:
        do_not_chase = current * Decimal("1.0020")
    if explicit_do_not_chase is not None:
        do_not_chase = min(do_not_chase, explicit_do_not_chase) if do_not_chase is not None else explicit_do_not_chase
    if do_not_chase is None:
        missing.append("do_not_chase_above")
    elif current > do_not_chase:
        hard.append("do_not_chase_hard_violation")

    if str(pending.get("status") or "").lower() in {"invalidated", "expired", "cancelled", "replaced"}:
        hard.append(f"pending_plan_{pending.get('status')}")

    would_if_relaxed = bool(current and spread is not None and invalidation is not None and (zone_low is not None or zone_high is not None))
    if missing or hard:
        return build_default_no_plan(
            ticker=ticker,
            reason="starter_probe_hard_conditions_not_met",
            source=source,
            missing_fields=missing,
            hard_blockers=hard,
            soft_warnings=soft,
            would_be_starter_probe_if_relaxed=would_if_relaxed,
        )

    setup_type = normalize_setup_type(synth.get("setup_type") or entry_gate.get("setup_type") or "reclaim_reversal")
    plan_type = "starter_reclaim_probe" if setup_type in {"reclaim_reversal", "support_sweep_reclaim", "mean_reversion"} else "starter_probe"
    trigger_price = min(max(current, zone_low), do_not_chase)
    target = current + ((current - invalidation) * Decimal("1.60"))
    confidence = 58
    if not soft:
        confidence = 64
    elif len(soft) >= 2:
        confidence = 54

    return {
        "plan_type": plan_type,
        "plan_action": "prepare_reclaim" if plan_type == "starter_reclaim_probe" else "prepare_buy",
        "ticker": ticker,
        "side": "BUY",
        "setup_type": setup_type,
        "entry_zone_low": float(zone_low),
        "entry_zone_high": float(zone_high),
        "trigger_price": float(trigger_price),
        "trigger": f"BUY only if price holds/reclaims {trigger_price} inside {zone_source}",
        "do_not_chase_above": float(do_not_chase),
        "invalidation_price": float(invalidation),
        "stop_loss": float(invalidation),
        "stop_loss_price": float(invalidation),
        "take_profit_1": float(target),
        "take_profit_2": None,
        "max_quote_size": float(starter_quote),
        "max_size_quote": float(starter_quote),
        "invalidation": f"Invalid below {invalidation} from {invalidation_source}",
        "monitoring_rules": [
            "keep size at starter/probe cap",
            "cancel/wait if price trades above do_not_chase_above before entry",
            "wait if spread/liquidity deteriorates before deterministic execution checks",
        ],
        "risk_notes": [
            f"stop_distance_pct={float(((current - invalidation) / current) * Decimal('100')):.2f}",
            f"spread_pct={spread}",
        ],
        "confidence": confidence,
        "planner_confidence": confidence,
        "planner_blockers": [],
        "must_not_trade_if": [
            "market data is stale",
            "spread exceeds max_spread_pct",
            "price is above do_not_chase_above",
            "price breaks invalidation/stop before entry",
            "open-order, duplicate-order, cooldown, or position-limit blocker is present",
        ],
        "why_plan_is_valid": "current price, acceptable spread/liquidity, entry/support zone, close invalidation, no-chase cap, and starter quote rails are defined",
        "why_size_is_small": "soft/mixed evidence is handled with minimum starter/probe sizing instead of full conviction sizing",
        "reason": "Deterministic starter/probe fallback built because hard risk is defined while soft warnings do not justify no_plan.",
        "no_plan_reason": "",
        "missing_fields": [],
        "hard_blockers": [],
        "soft_warnings": soft,
        "would_be_starter_probe_if_relaxed": False,
        "source": source,
        "plan_status": "active",
        "pattern_alignment": "mixed" if soft else "bullish",
    }


def is_valid_entry_trade_plan(plan: Dict[str, Any]) -> bool:
    if not isinstance(plan, dict):
        return False
    if str(plan.get("plan_action") or "").lower() not in ENTRY_PLAN_ACTIONS:
        return False
    if str(plan.get("side") or "").upper() != "BUY":
        return False
    # Core identity fields: must be non-None and non-empty string
    for key in ("ticker", "setup_type"):
        if plan.get(key) in (None, ""):
            return False
    # Core numeric price/size fields: must be non-None and positive
    # Advisory fields (risk_notes, why_plan_is_valid, why_size_is_small, planner_blockers,
    # must_not_trade_if) are intentionally excluded — an empty planner_blockers list means
    # no blockers (a clean plan), and advisory text fields may be omitted by the LLM.
    # do_not_chase_above and take_profit_1 are ALSO excluded on purpose: TRADE_PLANNER_PROMPT
    # explicitly allows numeric fields other than max_size_quote/confidence to be null.
    # A resting-limit BUY never fills worse than its limit, so a missing chase-ceiling is not
    # a capital-risk gap, and profit targets are managed by the exit/trailing layer, not TP1.
    # Requiring them here (the pre-f13e1f7 bug class) silently rejected otherwise-valid plans.
    for key in (
        "entry_zone_low",
        "entry_zone_high",
        "trigger_price",
        "invalidation_price",
        "stop_loss_price",
        "max_quote_size",
        "planner_confidence",
    ):
        val = plan.get(key)
        if val is None:
            return False
        try:
            if float(val) <= 0:
                return False
        except (ValueError, TypeError):
            return False
    return True


def normalize_setup_type(value: Any) -> str:
    setup_type = str(value or "unclear").strip().lower()
    return setup_type if setup_type in ALLOWED_SETUP_TYPES else "unclear"


def normalize_plan_action(value: Any) -> str:
    action = str(value or "no_plan").strip().lower()
    return action if action in ALLOWED_PLAN_ACTIONS else "no_plan"


def normalize_trade_plan(
    payload: Any,
    *,
    ticker: Optional[str] = None,
    max_size_quote: Any = None,
    min_size_quote: Any = None,
    source: str = "llm_trade_planner",
) -> Dict[str, Any]:
    """
    Normalize untrusted LLM planner output into a safe, JSON-compatible plan.

    This function deliberately does not authorize execution. It only prepares a
    structured plan for the final judge and deterministic risk/firewall layers.
    Malformed, incomplete or unsafe planner output collapses to no_plan.
    """
    if not isinstance(payload, dict):
        return build_default_no_plan(ticker=ticker, reason="planner_payload_not_dict", source=source)

    action = normalize_plan_action(payload.get("plan_action"))
    expected_ticker = ticker or payload.get("ticker")
    payload_ticker = str(payload.get("ticker") or expected_ticker or "").strip() or None

    if ticker and payload_ticker and payload_ticker != ticker:
        return build_default_no_plan(
            ticker=ticker,
            reason=f"planner_ticker_mismatch:{payload_ticker}!={ticker}",
            source=source,
        )

    max_size = _to_quote_float(payload.get("max_size_quote", payload.get("max_quote_size")))
    hard_cap = _to_decimal(max_size_quote)
    if hard_cap is not None and max_size > float(hard_cap):
        max_size = float(hard_cap)

    min_size = _to_decimal(min_size_quote)
    confidence = _to_confidence(payload.get("confidence"))
    reason = str(payload.get("reason") or "").strip()

    plan = {
        "plan_type": str(payload.get("plan_type") or ("trade_plan" if action != "no_plan" else "no_plan")).strip(),
        "plan_action": action,
        "ticker": payload_ticker or ticker,
        "side": str(payload.get("side") or ("BUY" if action in ENTRY_PLAN_ACTIONS else "NONE")).strip().upper(),
        "setup_type": normalize_setup_type(payload.get("setup_type")),
        "entry_zone_low": _to_float_or_none(payload.get("entry_zone_low")),
        "entry_zone_high": _to_float_or_none(payload.get("entry_zone_high")),
        "trigger_price": _to_float_or_none(payload.get("trigger_price") or payload.get("trigger")),
        "trigger": str(payload.get("trigger") or "").strip(),
        "do_not_chase_above": _to_float_or_none(payload.get("do_not_chase_above")),
        "preferred_limit_price": _to_float_or_none(payload.get("preferred_limit_price")),
        "invalidation_price": _to_float_or_none(payload.get("invalidation_price") or payload.get("stop_loss_price") or payload.get("stop_loss")),
        "stop_loss": _to_float_or_none(payload.get("stop_loss")),
        "stop_loss_price": _to_float_or_none(payload.get("stop_loss_price") or payload.get("stop_loss")),
        "take_profit_1": _to_float_or_none(payload.get("take_profit_1")),
        "take_profit_2": _to_float_or_none(payload.get("take_profit_2")),
        "target_price_1": _to_float_or_none(payload.get("target_price_1") or payload.get("take_profit_1")),
        "target_price_2": _to_float_or_none(payload.get("target_price_2") or payload.get("take_profit_2")),
        "invalidation": str(payload.get("invalidation") or "").strip(),
        "max_quote_size": max_size,
        "max_size_quote": max_size,
        "monitoring_rules": _string_list(payload.get("monitoring_rules")),
        "risk_notes": _string_list(payload.get("risk_notes")),
        "confidence": confidence,
        "planner_confidence": _to_confidence(payload.get("planner_confidence", payload.get("confidence"))),
        "planner_blockers": _string_list(payload.get("planner_blockers")),
        "must_not_trade_if": _string_list(payload.get("must_not_trade_if")),
        "why_plan_is_valid": str(payload.get("why_plan_is_valid") or "").strip(),
        "why_size_is_small": str(payload.get("why_size_is_small") or "").strip(),
        "reason": reason or "Planner returned a normalized plan.",
        "no_plan_reason": str(payload.get("no_plan_reason") or (reason if action == "no_plan" else "")).strip(),
        "missing_fields": _string_list(payload.get("missing_fields")),
        "hard_blockers": _string_list(payload.get("hard_blockers")),
        "soft_warnings": _string_list(payload.get("soft_warnings")),
        "would_be_starter_probe_if_relaxed": bool(payload.get("would_be_starter_probe_if_relaxed")),
        "source": source,
        "plan_status": "active" if action in ACTIONABLE_PLAN_ACTIONS else "inactive",
        "pattern_alignment": str(payload.get("pattern_alignment") or "neutral").strip().lower() or "neutral",
        "entry_reason": str(payload.get("entry_reason") or "").strip(),
        "why_not_market_order": str(payload.get("why_not_market_order") or "").strip(),
        "why_resting_limit_is_or_is_not_valid": str(payload.get("why_resting_limit_is_or_is_not_valid") or "").strip(),
        "setup_expiry_minutes": _to_float_or_none(payload.get("setup_expiry_minutes")),
    }
    if plan["trigger_price"] is None:
        plan["trigger_price"] = plan["entry_zone_high"]
    if plan["invalidation_price"] is None:
        plan["invalidation_price"] = _to_float_or_none(_extract_price_from_text(plan["invalidation"]))
    if plan["stop_loss"] is None:
        plan["stop_loss"] = plan["invalidation_price"]
    if plan["stop_loss_price"] is None:
        plan["stop_loss_price"] = plan["stop_loss"]

    if plan["entry_zone_low"] is not None and plan["entry_zone_high"] is not None:
        if plan["entry_zone_low"] > plan["entry_zone_high"]:
            plan["entry_zone_low"], plan["entry_zone_high"] = plan["entry_zone_high"], plan["entry_zone_low"]

    # Actionable entry plans must have at least a trigger and invalidation. For
    # position management, a trigger may be less relevant, but invalidation/reason
    # must still be clear enough for the judge.
    if action in ENTRY_PLAN_ACTIONS:
        if not plan["trigger"] or not plan["invalidation"]:
            return build_default_no_plan(
                ticker=ticker or payload_ticker,
                reason="actionable_entry_plan_missing_trigger_or_invalidation",
                source=source,
                missing_fields=[k for k, v in {"trigger": plan["trigger"], "invalidation": plan["invalidation"]}.items() if not v],
            )
        if min_size is not None and Decimal(str(max_size)) < min_size:
            return build_default_no_plan(
                ticker=ticker or payload_ticker,
                reason=f"planner_max_size_below_min_trade:{max_size}<{min_size}",
                source=source,
                hard_blockers=[f"planner_max_size_below_min_trade:{max_size}<{min_size}"],
            )

    if action in {"reduce", "close", "manage_existing"}:
        if not plan["invalidation"] and not reason:
            return build_default_no_plan(
                ticker=ticker or payload_ticker,
                reason="position_management_plan_missing_reason_or_invalidation",
                source=source,
            )

    if action == "no_plan":
        plan["max_size_quote"] = 0.0
        plan["max_quote_size"] = 0.0
        plan["plan_status"] = "inactive"

    plan["valid_trade_plan"] = is_valid_entry_trade_plan(plan)

    return plan


def build_trade_planner_input(
    *,
    ticker: str,
    feature_pack: Dict[str, Any],
    deepseek_pack: Dict[str, Any],
    chart_patterns: Dict[str, Any],
    regime: Dict[str, Any],
    trend: Dict[str, Any],
    breakout: Dict[str, Any],
    meanrev: Dict[str, Any],
    bull: Dict[str, Any],
    bear: Dict[str, Any],
    synth: Dict[str, Any],
    existing_position: Optional[Dict[str, Any]] = None,
    recent_reflections: Optional[Dict[str, Any]] = None,
    decision_outcomes: Optional[Dict[str, Any]] = None,
    pending_trade_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return {
        "ticker": ticker,
        "feature_pack": feature_pack,
        "deepseek_pack": deepseek_pack,
        "chart_patterns": chart_patterns,
        "regime": regime,
        "trend": trend,
        "breakout": breakout,
        "meanrev": meanrev,
        "bull": bull,
        "bear": bear,
        "synth": synth,
        "existing_position": existing_position or {},
        "recent_reflections": recent_reflections or {},
        "decision_outcomes": decision_outcomes or {},
        "pending_trade_plan": pending_trade_plan or {},
    }
