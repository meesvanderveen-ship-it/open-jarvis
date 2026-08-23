from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bot.product_rules import canonical_product_rules, execution_feasibility_context

ZERO = Decimal("0")
DEFAULT_MAX_DISTANCE_FROM_MID_PCT = Decimal("0.0030")
DEFAULT_MAX_SPREAD_PCT = Decimal("0.0060")
DEFAULT_MIN_REWARD_TO_RISK = Decimal("1.20")
DEFAULT_MIN_REWARD_TO_FEE = Decimal("2.00")
DEFAULT_MAX_QUOTE = Decimal("25.00")

ENTRY_DECISION_LABELS = {
    "wait_no_setup",
    "wait_bad_market",
    "wait_trigger_not_ready_no_order",
    "wait_do_not_chase_no_order",
    "wait_insufficient_confirmation",
    "valid_setup_no_order_yet",
    "valid_setup_resting_entry_candidate",
    "valid_setup_pending_limit_entry",
    "prepare_resting_limit_entry",
    "prepare_retest_limit_entry",
    "prepare_pullback_limit_entry",
    "prepare_reclaim_retest_limit_entry",
    "prepare_breakout_retest_limit_entry",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _to_decimal(value: Any, default: Optional[str] = None) -> Optional[Decimal]:
    if value in (None, ""):
        if default is None:
            return None
        value = default
    try:
        out = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default) if default is not None else None
    if out.is_nan() or out.is_infinite():
        return Decimal(default) if default is not None else None
    return out


def _first_decimal(*values: Any) -> Optional[Decimal]:
    for value in values:
        dec = _to_decimal(value)
        if dec is not None and dec > ZERO:
            return dec
    return None


def _fmt(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _market_context(analysis: Dict[str, Any]) -> Dict[str, Any]:
    feature = _as_dict(analysis.get("feature_pack"))
    market = _as_dict(feature.get("market"))
    orderbook = _as_dict(feature.get("orderbook_context"))
    summary = _as_dict(feature.get("orderbook_summary"))
    return {"feature": feature, "market": market, "orderbook": orderbook, "summary": summary}


def _mid_bid_ask(analysis: Dict[str, Any], *, current_mid: Any = None, bid: Any = None, ask: Any = None) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    ctx = _market_context(analysis)
    market = ctx["market"]
    orderbook = ctx["orderbook"]
    summary = ctx["summary"]
    best_bid = _first_decimal(bid, market.get("best_bid"), orderbook.get("best_bid"), orderbook.get("top_bid_price"), summary.get("best_bid"))
    best_ask = _first_decimal(ask, market.get("best_ask"), orderbook.get("best_ask"), orderbook.get("top_ask_price"), summary.get("best_ask"))
    mid = _first_decimal(current_mid, market.get("mid_price"), orderbook.get("mid_price"), summary.get("mid_price"), market.get("last_price"), market.get("current_price"))
    if mid is None and best_bid is not None and best_ask is not None:
        mid = (best_bid + best_ask) / Decimal("2")
    return mid, best_bid, best_ask


def _spread_pct(analysis: Dict[str, Any], mid: Optional[Decimal], bid: Optional[Decimal], ask: Optional[Decimal], spread: Any = None) -> Optional[Decimal]:
    ctx = _market_context(analysis)
    raw = _first_decimal(spread, ctx["market"].get("spread_pct"), ctx["orderbook"].get("bid_ask_spread_pct"), ctx["summary"].get("spread_pct"))
    if raw is not None:
        return raw
    if mid and bid and ask and mid > ZERO:
        return (ask - bid) / mid
    return None


def _target_levels(plan: Dict[str, Any], judge: Dict[str, Any]) -> List[Decimal]:
    out: List[Decimal] = []
    for value in (
        plan.get("target_price_1"),
        plan.get("target_price_2"),
        plan.get("take_profit_1"),
        plan.get("take_profit_2"),
        judge.get("target_price_1"),
        judge.get("target_price_2"),
    ):
        dec = _to_decimal(value)
        if dec is not None and dec > ZERO and dec not in out:
            out.append(dec)
    return out


def _entry_level(plan: Dict[str, Any], judge: Dict[str, Any], mid: Optional[Decimal], bid: Optional[Decimal]) -> Tuple[Optional[Decimal], str]:
    explicit = _first_decimal(judge.get("preferred_limit_price"), plan.get("preferred_limit_price"), plan.get("limit_price"), plan.get("entry_price"))
    if explicit is not None:
        return explicit, "preferred_limit_price"
    low = _to_decimal(plan.get("entry_zone_low") or judge.get("entry_zone_low"))
    high = _to_decimal(plan.get("entry_zone_high") or judge.get("entry_zone_high"))
    if low is not None and high is not None and low > ZERO and high > ZERO:
        lower = min(low, high)
        upper = max(low, high)
        if mid is not None and lower <= mid <= upper:
            return min(mid, upper), "entry_zone_mid_or_current"
        return (lower + upper) / Decimal("2"), "entry_zone_midpoint"
    support = _first_decimal(plan.get("support_level"), judge.get("support_level"))
    if support is not None:
        return support, "support"
    return None, ""


def classify_entry_decision(analysis: Dict[str, Any]) -> str:
    judge = _as_dict(analysis.get("judge"))
    plan = _as_dict(analysis.get("trade_plan"))
    text = " ".join(
        str(x)
        for x in (
            _as_list(judge.get("reasons"))
            + _as_list(judge.get("judge_reasons"))
            + _as_list(judge.get("must_reject_if"))
            + _as_list(plan.get("reason"))
            + _as_list(plan.get("hard_blockers"))
            + _as_list(plan.get("planner_blockers"))
            + [judge.get("trigger_wait_reason"), plan.get("no_plan_reason")]
        )
        if x
    ).lower()
    action = str(plan.get("plan_action") or "no_plan").lower()
    if "do_not_chase" in text or "do not chase" in text or "chase risk" in text:
        return "wait_do_not_chase_no_order"
    if "trigger_not_ready" in text or "trigger not ready" in text or "trigger is not ready" in text or "fresh reclaim" in text or "confirmation is missing" in text:
        return "wait_trigger_not_ready_no_order"
    if "spread" in text and ("wide" in text or "too high" in text):
        return "wait_bad_market"
    if "confirmation" in text or "confirm" in text:
        return "wait_insufficient_confirmation"
    if action in {"prepare_buy", "prepare_reclaim", "prepare_breakout", "prepare_mean_reversion"}:
        return "valid_setup_no_order_yet"
    return "wait_no_setup"


def recommended_entry_type(analysis: Dict[str, Any]) -> str:
    setup = str(_as_dict(analysis.get("trade_plan")).get("setup_type") or _as_dict(analysis.get("judge")).get("setup_type") or "").lower()
    trigger = str(_as_dict(analysis.get("trade_plan")).get("trigger") or _as_dict(analysis.get("judge")).get("trigger") or "").lower()
    if "breakout" in setup or "breakout" in trigger:
        return "prepare_breakout_retest_limit_entry"
    if "reclaim" in setup or "reclaim" in trigger:
        return "prepare_reclaim_retest_limit_entry"
    if "pullback" in setup or "pullback" in trigger:
        return "prepare_pullback_limit_entry"
    if "mean" in setup or "support" in setup:
        return "prepare_retest_limit_entry"
    return "prepare_resting_limit_entry"


def determine_entry_route_type(
    *,
    analysis: Dict[str, Any],
    entry: Optional[Decimal],
    mid: Optional[Decimal],
) -> str:
    plan = _as_dict(analysis.get("trade_plan"))
    judge = _as_dict(analysis.get("judge"))
    setup = str(plan.get("setup_type") or judge.get("setup_type") or "").lower()
    trigger_text = str(plan.get("trigger") or judge.get("trigger") or judge.get("trigger_wait_reason") or "").lower()
    trigger_price = _first_decimal(plan.get("trigger_price"), judge.get("trigger_price"))
    has_zone = any(plan.get(k) not in (None, "") or judge.get(k) not in (None, "") for k in ("entry_zone_low", "entry_zone_high", "preferred_limit_price"))

    if entry is None or mid is None or mid <= ZERO:
        if trigger_price is not None and mid is not None and trigger_price > mid:
            return "breakout_confirmation_wait"
        return "no_order"
    if trigger_price is not None and trigger_price > mid and not has_zone:
        return "breakout_confirmation_wait"
    if "breakout" in setup or "breakout" in trigger_text:
        if entry <= mid:
            return "breakout_retest_limit"
        return "breakout_confirmation_wait"
    if "reclaim" in setup or "reclaim" in trigger_text or "retest" in setup or "retest" in trigger_text:
        return "reclaim_retest_limit"
    if entry < mid or "pullback" in setup or "support" in setup or "mean" in setup:
        return "pullback_limit"
    return "no_order"


def _has_open_position_same_ticker(open_positions: Sequence[Dict[str, Any]], ticker: str) -> bool:
    ticker = str(ticker or "").upper()
    for pos in open_positions:
        if not isinstance(pos, dict):
            continue
        if str(pos.get("ticker") or pos.get("product_id") or "").upper() != ticker:
            continue
        status = str(pos.get("status") or "open").lower()
        base = _first_decimal(pos.get("position_size_base"), pos.get("size_base"), pos.get("base_size"), pos.get("bot_managed_base"))
        if status in {"open", "active"} and base is not None and base > ZERO:
            return True
    return False


def build_resting_limit_entry_preview(
    *,
    ticker: str,
    analysis: Dict[str, Any],
    current_mid: Any = None,
    bid: Any = None,
    ask: Any = None,
    spread_pct: Any = None,
    open_orders_count: int = 0,
    open_positions: Optional[Sequence[Dict[str, Any]]] = None,
    new_orders_this_cycle: int = 0,
    max_quote: Any = DEFAULT_MAX_QUOTE,
    max_open_orders: int = 4,
    max_new_orders_per_cycle: int = 1,
    max_distance_from_mid_pct: Any = DEFAULT_MAX_DISTANCE_FROM_MID_PCT,
    max_spread_pct: Any = DEFAULT_MAX_SPREAD_PCT,
    min_reward_to_risk: Any = DEFAULT_MIN_REWARD_TO_RISK,
    min_reward_to_fee: Any = DEFAULT_MIN_REWARD_TO_FEE,
    roundtrip_fee_pct: Any = "0.012",
    block_with_open_position_same_ticker: bool = True,
    product_rules: Optional[Dict[str, Any]] = None,
    recent_exchange_rejections: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    analysis = analysis if isinstance(analysis, dict) else {}
    judge = _as_dict(analysis.get("judge"))
    plan = _as_dict(analysis.get("trade_plan"))
    blockers: List[str] = []
    warnings: List[str] = []
    side = str(plan.get("side") or judge.get("side") or "").upper()
    decision_label = classify_entry_decision(analysis)
    entry_type = recommended_entry_type(analysis)
    mid, best_bid, best_ask = _mid_bid_ask(analysis, current_mid=current_mid, bid=bid, ask=ask)
    spread = _spread_pct(analysis, mid, best_bid, best_ask, spread_pct)
    entry, entry_source = _entry_level(plan, judge, mid, best_bid)
    entry_route_type = determine_entry_route_type(analysis=analysis, entry=entry, mid=mid)
    invalidation = _first_decimal(judge.get("invalidation_price"), plan.get("invalidation_price"), plan.get("stop_loss_price"), plan.get("stop_loss"), judge.get("cancel_if_price_below"))
    targets = _target_levels(plan, judge)
    do_not_chase = _first_decimal(judge.get("do_not_chase_above"), plan.get("do_not_chase_above"))
    zone_low = _to_decimal(plan.get("entry_zone_low") or judge.get("entry_zone_low"))
    if entry is not None and do_not_chase is not None and entry > do_not_chase and zone_low is not None and zone_low <= do_not_chase:
        entry = do_not_chase
        entry_source = f"{entry_source}_capped_by_do_not_chase"
    quote = _first_decimal(judge.get("size_quote"), plan.get("max_quote_size"), plan.get("max_size_quote")) or ZERO
    max_quote_dec = _to_decimal(max_quote, str(DEFAULT_MAX_QUOTE)) or DEFAULT_MAX_QUOTE
    max_dist = _to_decimal(max_distance_from_mid_pct, str(DEFAULT_MAX_DISTANCE_FROM_MID_PCT)) or DEFAULT_MAX_DISTANCE_FROM_MID_PCT
    max_spread = _to_decimal(max_spread_pct, str(DEFAULT_MAX_SPREAD_PCT)) or DEFAULT_MAX_SPREAD_PCT
    min_rr = _to_decimal(min_reward_to_risk, str(DEFAULT_MIN_REWARD_TO_RISK)) or DEFAULT_MIN_REWARD_TO_RISK
    min_rf = _to_decimal(min_reward_to_fee, str(DEFAULT_MIN_REWARD_TO_FEE)) or DEFAULT_MIN_REWARD_TO_FEE
    fee = _to_decimal(roundtrip_fee_pct, "0.012") or Decimal("0.012")

    if side != "BUY":
        blockers.append("buy_entries_only_no_naked_sell")
    if entry is None or entry <= ZERO:
        blockers.append("entry_level_missing")
    if invalidation is None or invalidation <= ZERO:
        blockers.append("invalidation_level_missing")
    if not targets:
        blockers.append("target_level_missing")
    if mid is None or mid <= ZERO:
        blockers.append("current_mid_missing")
    if spread is None:
        blockers.append("spread_missing")
    elif spread > max_spread:
        blockers.append("spread_too_wide")
    if quote <= ZERO:
        blockers.append("quote_size_missing")
    elif quote > max_quote_dec:
        blockers.append("quote_size_above_max")
    if open_orders_count >= int(max_open_orders):
        blockers.append("max_open_orders_reached")
    if new_orders_this_cycle >= int(max_new_orders_per_cycle):
        blockers.append("max_new_orders_per_cycle_reached")
    if block_with_open_position_same_ticker and _has_open_position_same_ticker(open_positions or [], ticker):
        blockers.append("open_position_same_ticker_present")

    distance = None
    technical_retest_zone = entry_route_type in {"pullback_limit", "reclaim_retest_limit", "breakout_retest_limit"}
    if entry is not None and mid is not None and mid > ZERO:
        distance = abs(mid - entry) / mid
        if distance > max_dist and not technical_retest_zone:
            blockers.append("entry_too_far_from_mid")
        elif distance > max_dist and technical_retest_zone:
            warnings.append("entry_outside_max_mid_distance_but_inside_technical_retest_route")
    if do_not_chase is not None and mid is not None and mid > do_not_chase:
        if entry is None or entry > do_not_chase:
            blockers.append("do_not_chase_above_breached")
        else:
            warnings.append("current_mid_above_do_not_chase_only_lower_resting_limit_allowed")
    if entry is not None and do_not_chase is not None and entry > do_not_chase:
        blockers.append("entry_level_above_do_not_chase")
    if entry is not None and invalidation is not None and invalidation >= entry:
        blockers.append("invalidation_not_below_entry")

    fp = _as_dict(analysis.get("feature_pack"))
    dc = _as_dict(fp.get("decision_context"))
    rules = product_rules or dc.get("product_rules") or fp.get("product_rules") or fp.get("exchange_rules") or {}
    product_rule_context = canonical_product_rules(str(ticker or "").upper(), rules)
    recent_rejections = recent_exchange_rejections if recent_exchange_rejections is not None else _as_list(dc.get("recent_exchange_rejections"))
    execution_feasibility = execution_feasibility_context(
        str(ticker or "").upper(),
        quote,
        entry or ZERO,
        product_rule_context,
        max_quote_size=max_quote_dec,
    )
    if not product_rule_context.get("precision_context_available"):
        blockers.append("product_precision_context_missing")
    if execution_feasibility.get("blockers"):
        blockers.extend([f"execution_feasibility:{b}" for b in execution_feasibility.get("blockers") or []])

    reward_to_risk = None
    reward_to_fee = None
    if entry is not None and invalidation is not None and targets and entry > ZERO:
        risk = entry - invalidation
        reward = max(targets) - entry
        if risk <= ZERO:
            blockers.append("risk_not_positive")
        elif reward <= ZERO:
            blockers.append("target_not_above_entry")
        else:
            reward_to_risk = reward / risk
            reward_to_fee = (reward / entry) / fee if fee > ZERO else None
            if reward_to_risk < min_rr:
                blockers.append("reward_to_risk_too_low")
            if reward_to_fee is not None and reward_to_fee < min_rf:
                blockers.append("reward_to_fee_too_low")

    eligible = not blockers
    cancel_if = [
        "setup_invalidated",
        "price_moves_away_without_fill",
        "spread_too_wide",
        "liquidity_worsens",
        "higher_timeframe_invalidates",
        "max_age_exceeded",
    ]
    return {
        "generated_at": now_iso(),
        "entry_order_policy": "resting_limit_maker_preview",
        "eligible": bool(eligible),
        "reason": "eligible_resting_limit_entry_preview" if eligible else (blockers[0] if blockers else "not_eligible"),
        "blockers": blockers,
        "warnings": warnings,
        "ticker": str(ticker or "").upper(),
        "side": "BUY" if side == "BUY" else side,
        "entry_decision_label": "valid_setup_resting_entry_candidate" if eligible else decision_label,
        "entry_route_type": entry_route_type if eligible else ("breakout_confirmation_wait" if entry_route_type == "breakout_confirmation_wait" else "no_order"),
        "setup_type": str(plan.get("setup_type") or judge.get("setup_type") or "unknown"),
        "recommended_entry_type": entry_type if eligible else ("valid_setup_no_order_yet" if decision_label.startswith("wait_trigger") else decision_label),
        "entry_level": _fmt(entry),
        "entry_level_source": entry_source,
        "current_mid": _fmt(mid),
        "best_bid": _fmt(best_bid),
        "best_ask": _fmt(best_ask),
        "spread_pct": _fmt(spread),
        "distance_from_mid_pct": _fmt(distance),
        "max_distance_allowed_pct": _fmt(max_dist),
        "invalidation_level": _fmt(invalidation),
        "target_levels": [_fmt(x) for x in targets],
        "expected_reward_to_risk": _fmt(reward_to_risk),
        "expected_reward_to_fee": _fmt(reward_to_fee),
        "quote_size": _fmt(quote),
        "max_quote": _fmt(max_quote_dec),
        "post_only": True,
        "product_rules": product_rule_context,
        "recent_exchange_rejections": recent_rejections,
        "execution_feasibility": execution_feasibility,
        "time_in_force": "GTC_or_limited",
        "ttl_minutes": 60,
        "cancel_if": cancel_if,
        "replace_if": ["bounded_retest_level_improves_once", "same_thesis_better_maker_price"],
        "would_submit": False,
        "pending_entry_preview_created": bool(eligible),
        "live_resting_entry_submit_enabled": False,
        "live_resting_entry_submit_attempted": False,
        "live_submission_attempted": False,
        "coinbase_call_attempted": False,
        "lifecycle_model": [
            "pending_entry_created_preview",
            "live_submit_only_if_env_ack_operator_later_allows",
            "open_entry_order_monitored",
            "cancel_if_stale_or_invalidated",
            "bounded_replace_same_thesis_only",
            "fill_detected_by_d1_or_c43_reconciliation",
            "position_opened",
            "d2_exit_plan_generated",
            "d3_limit_exit_orders_guarded",
            "controlled_stop_route_separate",
        ],
    }


def enrich_analysis_with_orderbook_entry_preview(analysis: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    clone = dict(analysis or {})
    ticker = str(clone.get("ticker") or _as_dict(clone.get("trade_plan")).get("ticker") or _as_dict(clone.get("feature_pack")).get("ticker") or "")
    clone["orderbook_entry_preview"] = build_resting_limit_entry_preview(ticker=ticker, analysis=clone, **kwargs)
    return clone


__all__ = [
    "ENTRY_DECISION_LABELS",
    "build_resting_limit_entry_preview",
    "classify_entry_decision",
    "enrich_analysis_with_orderbook_entry_preview",
    "recommended_entry_type",
]
