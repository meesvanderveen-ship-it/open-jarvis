from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.phase_d6_metrics import d6_metric_safety_flags


D6_MULTI_ORDER_INTENT_PHASE = "D6_multi_order_intent_preview_v1"
ZERO = Decimal("0")
ONE = Decimal("1")
OPEN_ORDER_STATUSES = {"planned", "pending", "submitted", "partially_filled", "open", "active", "new", "queued"}
FINAL_ORDER_STATUSES = {"filled", "done", "completed", "cancelled", "canceled", "expired", "failed", "rejected", "submit_rejected"}
RECOGNIZED_SETUP_FAMILIES = {
    "reclaim",
    "reclaim_reversal",
    "breakout",
    "pullback",
    "pullback_continuation",
    "support_retest",
    "support_reclaim",
    "range_reclaim",
    "mean_reversion",
    "trend_continuation",
    "compression_breakout",
    "bounce",
}
SETUP_ALIASES = {
    "support_reclaim": "range_reclaim",
    "reclaim": "reclaim_reversal",
    "pullback": "pullback_continuation",
    "continuation": "trend_continuation",
}
MOMENTUM_DEPENDENT_SETUPS = {"breakout", "compression_breakout", "reclaim_reversal", "range_reclaim"}
ENTRY_GATE_HARD_DECISIONS = {"reject", "rejected", "block", "blocked", "hard_reject", "do_not_trade", "no_trade"}
ENTRY_GATE_SOFT_DECISIONS = {"watch", "analyze", "analyse", "wait", "hold", "monitor"}


DEFAULT_POLICY = {
    "preview_only": True,
    "max_open_orders_total": 5,
    "max_quote_per_order": "20.00",
    "max_total_buy_quote_reserved": "100.00",
    "max_open_orders_per_ticker": 1,
    "max_new_orders_per_cycle": 2,
    "default_buy_quote": "20.00",
    "max_spread_pct": "0.0060",
    "min_confidence": 62,
    "min_edge_score": 58,
    "min_reward_risk": "1.20",
    "maker_orders_preferred": True,
    "market_orders_enabled": False,
    "sell_live_execution_enabled": False,
    "buy_live_execution_enabled": False,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def decimal_str(value: Any) -> str:
    text = format(to_decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    return value


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_decimal(*values: Any, default: str = "0") -> Decimal:
    for value in values:
        dec = to_decimal(value, "0")
        if dec > ZERO:
            return dec
    return Decimal(default)


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _pct_distance(a: Decimal, b: Decimal) -> Decimal:
    if b <= ZERO:
        return ZERO
    return abs(a - b) / b


def _extract_market(candidate: Dict[str, Any]) -> Dict[str, Any]:
    feature = as_dict(candidate.get("feature_pack") or candidate.get("features"))
    market = as_dict(feature.get("market") or candidate.get("market"))
    orderbook = as_dict(feature.get("orderbook_context") or candidate.get("orderbook_context") or candidate.get("orderbook"))
    if "top_of_book" in orderbook:
        top = as_dict(orderbook.get("top_of_book"))
        depth = as_dict(orderbook.get("depth"))
        merged = {**orderbook, **top, **depth}
        orderbook = merged
    structure = as_dict(feature.get("structure") or candidate.get("structure"))
    micro = as_dict(feature.get("microstructure") or candidate.get("microstructure"))
    risk = as_dict(feature.get("risk_context") or candidate.get("risk_context"))
    return {
        "feature_pack": feature,
        "market": market,
        "orderbook": orderbook,
        "structure": structure,
        "microstructure": micro,
        "risk_context": risk,
    }


def _extract_latest_volume_ratio(micro: Dict[str, Any], candidate: Dict[str, Any]) -> Decimal:
    values: List[Decimal] = []
    for key in ("15m", "1h"):
        frame = as_dict(micro.get(key))
        values.append(to_decimal(frame.get("volume_vs_avg"), "0"))
    orderbook = as_dict(candidate.get("orderbook_summary"))
    volume = as_dict(orderbook.get("volume_confirmation"))
    values.append(to_decimal(volume.get("15m_volume_vs_avg"), "0"))
    values.append(to_decimal(volume.get("1h_volume_vs_avg"), "0"))
    return max(values) if values else ZERO


def _has_positive_momentum(micro: Dict[str, Any], candidate: Dict[str, Any]) -> bool:
    for key in ("15m", "1h"):
        frame = as_dict(micro.get(key))
        if str(frame.get("net_close_direction") or "").lower() == "up":
            return True
    evidence = as_dict(candidate.get("evidence"))
    bullish = [str(x).lower() for x in as_list(evidence.get("bullish_evidence"))]
    bearish = [str(x).lower() for x in as_list(evidence.get("bearish_evidence"))]
    return bool(bullish) and len(bullish) >= len(bearish)


def _setup_family(candidate: Dict[str, Any]) -> str:
    entry_gate = as_dict(candidate.get("entry_gate"))
    trade_plan = as_dict(candidate.get("trade_plan"))
    judge = as_dict(candidate.get("judge"))
    analysis = as_dict(candidate.get("analysis"))
    raw = _first_text(
        candidate.get("setup_family"),
        candidate.get("setup_type"),
        trade_plan.get("setup_family"),
        trade_plan.get("setup_type"),
        entry_gate.get("setup_type"),
        analysis.get("setup_family"),
        analysis.get("setup_type"),
        analysis.get("strategy"),
        judge.get("strategy"),
    )
    normalized = raw.lower().replace(" ", "_").replace("-", "_") if raw else ""
    if normalized and normalized not in {"unknown", "unclear", "none", "n/a"}:
        return SETUP_ALIASES.get(normalized, normalized)

    text_parts: List[str] = []
    for key in ("strategy", "reason", "reasons", "rationale", "summary", "level_context"):
        value = candidate.get(key)
        if value:
            text_parts.append(json.dumps(value, sort_keys=True).lower() if isinstance(value, (dict, list)) else str(value).lower())
    for source in (entry_gate, analysis, trade_plan, judge):
        if source:
            text_parts.append(json.dumps(source, sort_keys=True).lower())
    text = " ".join(text_parts)
    keyword_map = [
        ("trend_continuation", ("trend continuation", "continuation", "higher low", "pullback continuation")),
        ("reclaim_reversal", ("reclaim reversal", "reclaim", "reversal")),
        ("mean_reversion", ("mean reversion", "oversold", "reversion")),
        ("range_reclaim", ("range reclaim", "range support", "range low reclaim")),
        ("support_retest", ("support retest", "retest support", "support test")),
        ("pullback_continuation", ("pullback", "dip buy")),
        ("breakout", ("breakout", "break out", "break above")),
    ]
    for setup, keywords in keyword_map:
        if any(keyword in text for keyword in keywords):
            return setup
    return "unclear"


def _side(candidate: Dict[str, Any]) -> str:
    judge = as_dict(candidate.get("judge"))
    side = _first_text(candidate.get("side"), candidate.get("intent_side"), judge.get("side")).upper()
    if side in {"BUY", "SELL"}:
        return side
    position_action = str(candidate.get("position_action") or "").lower()
    if position_action in {"close", "reduce", "sell"}:
        return "SELL"
    return "BUY"


def _preferred_order_type(candidate: Dict[str, Any]) -> str:
    raw = str(candidate.get("preferred_order_type") or candidate.get("order_type") or "").strip().lower()
    if raw in {"market", "market_buy", "market_sell"}:
        return "market"
    return "limit_maker"


def _policy(policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = dict(DEFAULT_POLICY)
    merged.update(policy or {})
    return merged


def _open_orders(raw: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    data = as_dict(raw)
    orders = data.get("orders")
    if isinstance(orders, dict):
        values = list(orders.values())
    elif isinstance(orders, list):
        values = orders
    else:
        values = []
    out: List[Dict[str, Any]] = []
    for order in values:
        if not isinstance(order, dict):
            continue
        status = str(order.get("status") or order.get("order_status") or "").strip().lower()
        if status in OPEN_ORDER_STATUSES or (status and status not in FINAL_ORDER_STATUSES and to_decimal(order.get("remaining_size"), "0") > ZERO):
            out.append(order)
    return out


def _order_ticker(order: Dict[str, Any]) -> str:
    return normalize_ticker(order.get("ticker") or order.get("product_id") or order.get("product"))


def _order_side(order: Dict[str, Any]) -> str:
    return str(order.get("side") or "").strip().upper()


def _order_quote_remaining(order: Dict[str, Any]) -> Decimal:
    value = _first_decimal(order.get("remaining_quote"), order.get("size_quote"), order.get("quote_size"))
    if value > ZERO:
        return value
    price = _first_decimal(order.get("limit_price"), order.get("price"))
    base = _first_decimal(order.get("remaining_size"), order.get("size_base"), order.get("base_size"))
    return price * base if price > ZERO and base > ZERO else ZERO


def _order_base_remaining(order: Dict[str, Any]) -> Decimal:
    return _first_decimal(order.get("remaining_size"), order.get("size_base"), order.get("base_size"))


def build_reservation_preview(
    *,
    open_orders_state: Optional[Dict[str, Any]] = None,
    positions_state: Optional[Dict[str, Any]] = None,
    quote_available: Any = None,
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rules = _policy(policy)
    orders = _open_orders(open_orders_state)
    buy_reserved = ZERO
    sell_reserved = ZERO
    by_ticker: Dict[str, int] = {}
    buy_by_ticker: Dict[str, str] = {}
    sell_by_ticker: Dict[str, str] = {}
    open_order_summaries: List[Dict[str, Any]] = []
    for order in orders:
        ticker = _order_ticker(order)
        side = _order_side(order)
        by_ticker[ticker] = by_ticker.get(ticker, 0) + 1
        quote = _order_quote_remaining(order)
        base = _order_base_remaining(order)
        if side == "BUY":
            buy_reserved += quote
            buy_by_ticker[ticker] = decimal_str(to_decimal(buy_by_ticker.get(ticker), "0") + quote)
        if side == "SELL":
            sell_reserved += base
            sell_by_ticker[ticker] = decimal_str(to_decimal(sell_by_ticker.get(ticker), "0") + base)
        open_order_summaries.append(
            {
                "ticker": ticker,
                "side": side,
                "status": order.get("status"),
                "quote_remaining": decimal_str(quote),
                "base_remaining": decimal_str(base),
                "client_order_id": order.get("client_order_id"),
                "exchange_order_id": order.get("exchange_order_id") or order.get("order_id"),
            }
        )

    quote_cap = to_decimal(rules["max_total_buy_quote_reserved"])
    available_hint = to_decimal(quote_available, str(quote_cap))
    free_by_cap = max(ZERO, quote_cap - buy_reserved)
    free_quote = min(max(ZERO, available_hint), free_by_cap)
    positions = as_dict(positions_state)
    base_available: Dict[str, str] = {}
    for ticker, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        base = _first_decimal(pos.get("bot_managed_base"), pos.get("position_size_base"), pos.get("size_base"))
        reserved = to_decimal(sell_by_ticker.get(normalize_ticker(ticker)), "0")
        base_available[normalize_ticker(ticker)] = decimal_str(max(ZERO, base - reserved))

    blockers: List[str] = []
    if len(orders) >= int(rules["max_open_orders_total"]):
        blockers.append("max_open_order_cap_already_reached")
    if buy_reserved >= quote_cap:
        blockers.append("max_total_buy_quote_reserved_already_reached")

    return json_safe(
        {
            "open_order_count": len(orders),
            "open_order_count_by_ticker": by_ticker,
            "reserved_quote_open_buy_orders": buy_reserved,
            "reserved_base_open_sell_orders": sell_reserved,
            "reserved_quote_buy_by_ticker": buy_by_ticker,
            "reserved_base_sell_by_ticker": sell_by_ticker,
            "free_quote_available_for_new_buy_intents": free_quote,
            "max_open_orders_total": int(rules["max_open_orders_total"]),
            "max_quote_per_order": rules["max_quote_per_order"],
            "max_total_buy_quote_reserved": rules["max_total_buy_quote_reserved"],
            "max_open_orders_per_ticker": int(rules["max_open_orders_per_ticker"]),
            "max_new_orders_per_cycle": int(rules["max_new_orders_per_cycle"]),
            "base_available_after_sell_reservations": base_available,
            "open_orders": open_order_summaries,
            "blockers": blockers,
        }
    )


def _product_min_quote(candidate: Dict[str, Any], market: Dict[str, Any], risk_context: Dict[str, Any]) -> Decimal:
    return _first_decimal(
        candidate.get("min_order_quote"),
        candidate.get("quote_min_size"),
        market.get("min_order_quote"),
        market.get("quote_min_size"),
        risk_context.get("min_trade_quote_usdc"),
        default="1",
    )


def _quantize_quote(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _proposed_price(side: str, order_type: str, market: Dict[str, Any], orderbook: Dict[str, Any], trade_plan: Dict[str, Any]) -> Decimal:
    if order_type == "market":
        return _first_decimal(market.get("mid_price"), orderbook.get("mid_price"), market.get("price"), orderbook.get("best_ask"), orderbook.get("best_bid"))
    if side == "BUY":
        return _first_decimal(
            candidate_value(orderbook, "best_bid"),
            trade_plan.get("entry_zone_low"),
            trade_plan.get("trigger_price"),
            market.get("best_bid"),
            market.get("mid_price"),
            orderbook.get("mid_price"),
        )
    return _first_decimal(orderbook.get("best_ask"), market.get("best_ask"), orderbook.get("mid_price"), market.get("mid_price"))


def candidate_value(mapping: Dict[str, Any], key: str) -> Any:
    return mapping.get(key)


def _target_and_invalidation(side: str, candidate: Dict[str, Any], structure: Dict[str, Any], trade_plan: Dict[str, Any]) -> Tuple[Decimal, Decimal]:
    if side == "BUY":
        invalidation = _first_decimal(
            candidate.get("invalidation_reference"),
            trade_plan.get("stop_loss"),
            trade_plan.get("invalidation_price"),
            trade_plan.get("invalidation_level"),
            structure.get("nearest_support"),
            structure.get("support_1h"),
        )
        target = _first_decimal(
            candidate.get("target_reference"),
            trade_plan.get("take_profit_price"),
            trade_plan.get("take_profit_1"),
            trade_plan.get("target_price"),
            trade_plan.get("target_level"),
            structure.get("nearest_resistance"),
            structure.get("resistance_1h"),
        )
        return target, invalidation
    invalidation = _first_decimal(candidate.get("invalidation_reference"), trade_plan.get("invalidation_price"), trade_plan.get("stop_loss"))
    target = _first_decimal(candidate.get("target_reference"), trade_plan.get("take_profit_price"), trade_plan.get("target_price"))
    return target, invalidation


def _confidence(candidate: Dict[str, Any]) -> int:
    entry_gate = as_dict(candidate.get("entry_gate"))
    trade_plan = as_dict(candidate.get("trade_plan"))
    judge = as_dict(candidate.get("judge"))
    return int(max(to_decimal(candidate.get("confidence"), "0"), to_decimal(trade_plan.get("confidence"), "0"), to_decimal(entry_gate.get("confidence"), "0"), to_decimal(judge.get("confidence"), "0")))


def _entry_gate_decision(candidate: Dict[str, Any]) -> str:
    entry_gate = as_dict(candidate.get("entry_gate"))
    return str(entry_gate.get("decision") or candidate.get("entry_decision") or "").strip().lower()


def evaluate_order_intent_candidate(
    candidate: Dict[str, Any],
    *,
    reservation: Dict[str, Any],
    policy: Optional[Dict[str, Any]] = None,
    selected_so_far: int = 0,
) -> Dict[str, Any]:
    rules = _policy(policy)
    candidate = as_dict(candidate)
    ctx = _extract_market(candidate)
    market = ctx["market"]
    orderbook = ctx["orderbook"]
    structure = ctx["structure"]
    micro = ctx["microstructure"]
    risk_context = ctx["risk_context"]
    trade_plan = as_dict(candidate.get("trade_plan"))
    judge = as_dict(candidate.get("judge"))
    ticker = normalize_ticker(candidate.get("ticker") or market.get("ticker") or ctx["feature_pack"].get("ticker"))
    side = _side(candidate)
    setup_family = _setup_family(candidate)
    preferred_order_type = _preferred_order_type(candidate)
    confidence = _confidence(candidate)
    hard_blockers: List[str] = []
    soft_blockers: List[str] = []
    missing_data_blockers: List[str] = []
    warnings: List[str] = []

    if not ticker:
        missing_data_blockers.append("ticker_missing")
    if setup_family not in RECOGNIZED_SETUP_FAMILIES:
        soft_blockers.append("setup_family_unclear")
    if confidence < int(rules["min_confidence"]):
        soft_blockers.append("confidence_below_forming_intent_threshold")

    judge_decision = str(judge.get("decision") or "").strip().lower()
    if judge_decision in {"reject", "rejected", "block", "blocked"}:
        hard_blockers.append("hard_reject_from_existing_judge")
    entry_decision = _entry_gate_decision(candidate)
    if entry_decision in ENTRY_GATE_HARD_DECISIONS:
        hard_blockers.append("entry_gate_hard_reject")
    elif entry_decision in ENTRY_GATE_SOFT_DECISIONS:
        warnings.append(f"entry_gate_{entry_decision}_treated_as_preview_context")
    if judge_decision == "approve_trade":
        warnings.append("strict_approve_trade_route_available_but_not_used_by_preview_layer")

    spread_pct = _first_decimal(market.get("spread_pct"), market.get("bid_ask_spread_pct"), orderbook.get("spread_pct"), orderbook.get("bid_ask_spread_pct"))
    if spread_pct > to_decimal(rules["max_spread_pct"]):
        hard_blockers.append("wide_spread")
    spread_score = Decimal("100") if spread_pct == ZERO else max(ZERO, Decimal("100") - (spread_pct / to_decimal(rules["max_spread_pct"]) * Decimal("100")))

    pressure = str(orderbook.get("book_pressure") or "").strip().lower()
    imbalance = to_decimal(orderbook.get("depth_imbalance_top5"), "0")
    weak_orderbook = False
    if side == "BUY" and pressure in {"ask_heavy", "sell_heavy"} and imbalance < Decimal("-0.25"):
        hard_blockers.append("bad_orderbook_pressure")
        weak_orderbook = True
    if side == "SELL" and pressure in {"bid_heavy", "buy_heavy"} and imbalance > Decimal("0.25"):
        hard_blockers.append("bad_orderbook_pressure")
        weak_orderbook = True
    orderbook_score = max(ZERO, min(Decimal("100"), Decimal("70") + (imbalance * Decimal("50") if side == "BUY" else -imbalance * Decimal("50"))))

    volume_ratio = _extract_latest_volume_ratio(micro, candidate)
    momentum_ok = _has_positive_momentum(micro, candidate)
    if volume_ratio < Decimal("0.75") or not momentum_ok:
        missing_structure = not structure and not trade_plan
        volume_dead = volume_ratio > ZERO and volume_ratio < Decimal("0.35")
        momentum_dependent = setup_family in MOMENTUM_DEPENDENT_SETUPS
        hard_volume = (
            (volume_dead and not momentum_ok and weak_orderbook)
            or (momentum_dependent and not momentum_ok and volume_ratio < Decimal("0.90"))
            or (momentum_dependent and volume_dead)
            or (missing_structure and volume_dead and not momentum_ok)
        )
        if hard_volume:
            hard_blockers.append("bad_volume_or_momentum")
        else:
            soft_blockers.append("bad_volume_or_momentum")
    volume_score = min(Decimal("100"), max(ZERO, volume_ratio * Decimal("50") + (Decimal("25") if momentum_ok else ZERO)))

    price = _proposed_price(side, preferred_order_type, market, orderbook, trade_plan)
    target, invalidation = _target_and_invalidation(side, candidate, structure, trade_plan)
    if price <= ZERO:
        missing_data_blockers.append("proposed_price_missing")
    if invalidation <= ZERO:
        missing_data_blockers.append("missing_invalidation_reference")
    if target <= ZERO:
        missing_data_blockers.append("missing_target_reference")

    if side == "BUY":
        if invalidation > ZERO and price > ZERO and invalidation >= price:
            hard_blockers.append("invalidation_not_below_buy_price")
        if target > ZERO and price > ZERO and target <= price:
            hard_blockers.append("target_not_above_buy_price")
    else:
        if invalidation > ZERO and price > ZERO and invalidation <= price:
            warnings.append("sell_invalidation_not_above_price_for_risk_exit_context")

    do_not_chase = _first_decimal(candidate.get("do_not_chase_boundary"), trade_plan.get("do_not_chase_above"))
    if side == "BUY" and do_not_chase > ZERO:
        current = _first_decimal(market.get("mid_price"), market.get("price"), orderbook.get("mid_price"), price)
        if price > do_not_chase or current > do_not_chase:
            hard_blockers.append("do_not_chase_violation")

    reward = max(ZERO, target - price) if side == "BUY" else max(ZERO, price - target)
    risk = max(ZERO, price - invalidation) if side == "BUY" else max(ZERO, invalidation - price)
    reward_risk = (reward / risk) if risk > ZERO else ZERO
    if reward_risk < to_decimal(rules["min_reward_risk"]):
        soft_blockers.append("reward_risk_below_threshold")

    gross_edge_pct = (reward / price) if price > ZERO else ZERO
    cost_estimate_pct = max(spread_pct, Decimal("0.0001")) + Decimal("0.0020")
    edge_after_cost_pct = gross_edge_pct - cost_estimate_pct
    risk_score = max(ZERO, Decimal("100") - min(Decimal("100"), (risk / price * Decimal("1000")) if price > ZERO else Decimal("100")))
    edge_score = max(ZERO, min(Decimal("100"), edge_after_cost_pct * Decimal("1000") + reward_risk * Decimal("20")))
    if edge_score < to_decimal(rules["min_edge_score"]):
        soft_blockers.append("edge_score_below_threshold")

    quote_size = ZERO
    base_size = ZERO
    min_quote = _product_min_quote(candidate, market, risk_context)
    if side == "BUY":
        free_quote = to_decimal(reservation.get("free_quote_available_for_new_buy_intents"), "0")
        quote_size = min(to_decimal(rules["default_buy_quote"]), to_decimal(rules["max_quote_per_order"]), free_quote)
        quote_size = _quantize_quote(max(ZERO, quote_size))
        if quote_size > ZERO and price > ZERO:
            base_size = quote_size / price
        if quote_size > to_decimal(rules["max_quote_per_order"]):
            hard_blockers.append("max_order_quote_cap_exceeded")
        if quote_size < min_quote:
            hard_blockers.append("below_product_min_notional")
    else:
        raw_base = _first_decimal(candidate.get("size_base"), candidate.get("base_size"), candidate.get("position_size_base"))
        base_available = to_decimal(as_dict(reservation.get("base_available_after_sell_reservations")).get(ticker), "0")
        base_size = raw_base if raw_base > ZERO else base_available
        quote_size = base_size * price if price > ZERO else ZERO
        if base_size <= ZERO:
            hard_blockers.append("sell_base_balance_missing")
        if base_size > base_available:
            hard_blockers.append("sell_no_oversell_blocked")
        if quote_size > ZERO and quote_size < min_quote:
            hard_blockers.append("below_product_min_notional")

    per_ticker_count = int(as_dict(reservation.get("open_order_count_by_ticker")).get(ticker) or 0)
    if per_ticker_count >= int(rules["max_open_orders_per_ticker"]):
        hard_blockers.append("max_one_open_order_per_ticker")
    if int(reservation.get("open_order_count") or 0) >= int(rules["max_open_orders_total"]):
        hard_blockers.append("max_open_order_cap_reached")
    if selected_so_far >= int(rules["max_new_orders_per_cycle"]):
        hard_blockers.append("max_new_orders_per_cycle_reached")
    if side == "SELL" and to_decimal(as_dict(reservation.get("reserved_base_sell_by_ticker")).get(ticker), "0") > ZERO:
        hard_blockers.append("duplicate_sell_exit_rejected")

    market_order_preview = preferred_order_type == "market"
    if market_order_preview:
        hard_blockers.append("market_orders_disabled_by_default")
        hard_blockers.append("market_orders_future_ack_required")
        warnings.append("market_order_policy_requires_positive_edge_after_taker_fee_spread_slippage_and_urgency")

    if side == "SELL":
        warnings.append("sell_intents_preview_only_live_sell_disabled")

    blockers = hard_blockers + missing_data_blockers + soft_blockers
    accepted_for_preview = not hard_blockers and not missing_data_blockers and not soft_blockers
    near_miss = not accepted_for_preview and not hard_blockers and not missing_data_blockers and len(soft_blockers) <= 3
    status = "intent_preview_ready" if accepted_for_preview else "near_miss_intent" if near_miss else "candidate_rejected"
    if accepted_for_preview and side == "SELL":
        status = "sell_intent_preview_only"

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
    intent = {
        "intent_id": f"d6-intent-{uuid.uuid4().hex}",
        "ticker": ticker,
        "side": side,
        "setup_family": setup_family,
        "intent_family": "forming_setup_maker_probe" if side == "BUY" else "exit_or_reduce_preview",
        "confidence": confidence,
        "expected_value": {
            "gross_edge_pct": decimal_str(gross_edge_pct),
            "cost_estimate_pct": decimal_str(cost_estimate_pct),
            "edge_after_cost_pct": decimal_str(edge_after_cost_pct),
            "reward_risk": decimal_str(reward_risk),
        },
        "edge_score": decimal_str(edge_score),
        "risk_score": decimal_str(risk_score),
        "liquidity_score": decimal_str(spread_score),
        "volume_pattern_score": decimal_str(volume_score),
        "orderbook_score": decimal_str(orderbook_score),
        "preferred_order_type": preferred_order_type,
        "post_only_preferred": preferred_order_type != "market",
        "proposed_price": decimal_str(price),
        "proposed_size_quote": decimal_str(quote_size),
        "proposed_size_base": decimal_str(base_size),
        "invalidation_reference": decimal_str(invalidation),
        "target_reference": decimal_str(target),
        "do_not_chase_boundary": decimal_str(do_not_chase),
        "ttl_seconds": 1800,
        "expires_at": expires_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "blockers": blockers,
        "hard_blockers": hard_blockers,
        "missing_data_blockers": missing_data_blockers,
        "soft_blockers": soft_blockers,
        "missing_conditions": missing_data_blockers + soft_blockers,
        "warnings": warnings,
        "live_submit_eligibility": False,
        "live_submit_requires_future_ack": True,
        "preview_only": True,
        "market_order_preview": market_order_preview,
        "sell_order_preview": side == "SELL",
        "suggested_watch_level": decimal_str(price),
        "reason": _near_miss_reason(status, hard_blockers, missing_data_blockers, soft_blockers, price, volume_ratio, momentum_ok, reward_risk, edge_score),
        "explanation": _explanation(status, side, setup_family, hard_blockers, missing_data_blockers, soft_blockers, warnings),
        "status": status,
    }
    return json_safe(intent)


def _near_miss_reason(
    status: str,
    hard_blockers: List[str],
    missing_data_blockers: List[str],
    soft_blockers: List[str],
    price: Decimal,
    volume_ratio: Decimal,
    momentum_ok: bool,
    reward_risk: Decimal,
    edge_score: Decimal,
) -> str:
    if status in {"intent_preview_ready", "sell_intent_preview_only"}:
        return "All preview-only filters passed; live submit remains disabled."
    if hard_blockers:
        return f"Hard blocked by {', '.join(hard_blockers[:3])}; promotion requires removing the hard policy/safety failure."
    if missing_data_blockers:
        return f"Missing required references {', '.join(missing_data_blockers[:3])}; promotion requires valid price, invalidation and target data."
    details = []
    if "bad_volume_or_momentum" in soft_blockers:
        details.append(f"volume_ratio={decimal_str(volume_ratio)} momentum_ok={momentum_ok}")
    if "reward_risk_below_threshold" in soft_blockers:
        details.append(f"reward_risk={decimal_str(reward_risk)}")
    if "edge_score_below_threshold" in soft_blockers:
        details.append(f"edge_score={decimal_str(edge_score)}")
    if price <= ZERO:
        details.append("price reference absent")
    suffix = f" ({'; '.join(details)})" if details else ""
    return f"Near-miss candidate: improve {', '.join(soft_blockers[:3])}{suffix}."


def _explanation(
    status: str,
    side: str,
    setup_family: str,
    hard_blockers: List[str],
    missing_data_blockers: List[str],
    soft_blockers: List[str],
    warnings: List[str],
) -> str:
    if hard_blockers:
        return f"{side} {setup_family} hard rejected: {', '.join(hard_blockers[:5])}."
    if missing_data_blockers:
        return f"{side} {setup_family} missing required data: {', '.join(missing_data_blockers[:5])}."
    if soft_blockers:
        return f"{side} {setup_family} near-miss/rejected by soft conditions: {', '.join(soft_blockers[:5])}."
    suffix = " SELL remains preview-only." if side == "SELL" else " maker BUY remains preview-only."
    if warnings:
        suffix += f" Warnings: {', '.join(warnings[:3])}."
    return f"{status}: conservative {setup_family} intent passed preview filters;{suffix}"


def select_preview_intents(
    candidates: Iterable[Dict[str, Any]],
    *,
    reservation: Dict[str, Any],
    policy: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    preliminary: List[Dict[str, Any]] = []
    near_miss: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for candidate in candidates:
        intent = evaluate_order_intent_candidate(candidate, reservation=reservation, policy=policy, selected_so_far=0)
        if intent["status"] in {"intent_preview_ready", "sell_intent_preview_only"}:
            preliminary.append(intent)
        elif intent["status"] == "near_miss_intent":
            near_miss.append(intent)
        else:
            rejected.append(intent)

    preliminary.sort(key=lambda item: (to_decimal(item.get("edge_score"), "0"), to_decimal(item.get("risk_score"), "0")), reverse=True)
    near_miss.sort(key=lambda item: (to_decimal(item.get("edge_score"), "0"), to_decimal(item.get("confidence"), "0")), reverse=True)
    selected: List[Dict[str, Any]] = []
    selected_tickers: set[str] = set()
    for intent in preliminary:
        if len(selected) >= int(_policy(policy)["max_new_orders_per_cycle"]):
            blocked = dict(intent)
            blocked["status"] = "candidate_rejected"
            blocked["hard_blockers"] = list(blocked.get("hard_blockers") or []) + ["max_new_orders_per_cycle_reached"]
            blocked["blockers"] = list(blocked.get("blockers") or []) + ["max_new_orders_per_cycle_reached"]
            rejected.append(blocked)
            continue
        ticker = str(intent.get("ticker"))
        if ticker in selected_tickers:
            blocked = dict(intent)
            blocked["status"] = "candidate_rejected"
            blocked["hard_blockers"] = list(blocked.get("hard_blockers") or []) + ["max_one_open_order_per_ticker"]
            blocked["blockers"] = list(blocked.get("blockers") or []) + ["max_one_open_order_per_ticker"]
            rejected.append(blocked)
            continue
        selected.append(intent)
        selected_tickers.add(ticker)
    return selected, near_miss, rejected


def load_recent_analysis_candidates(path: str | Path, *, max_lines: int = 80) -> List[Dict[str, Any]]:
    source = Path(path)
    if not source.exists() or not source.is_file():
        return []
    rows: List[Dict[str, Any]] = []
    with source.open("r", encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()[-max_lines:]
    latest_by_ticker: Dict[str, Dict[str, Any]] = {}
    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        ticker = normalize_ticker(obj.get("ticker") or as_dict(obj.get("feature_pack")).get("ticker"))
        if ticker:
            latest_by_ticker[ticker] = obj
    for ticker in sorted(latest_by_ticker):
        rows.append(latest_by_ticker[ticker])
    return rows


def load_json_file(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _quote_available_from_candidates(candidates: Iterable[Dict[str, Any]]) -> Optional[str]:
    values: List[Decimal] = []
    for candidate in candidates:
        ctx = _extract_market(as_dict(candidate))
        risk = ctx["risk_context"]
        value = to_decimal(risk.get("available_quote_balance"), "0")
        if value > ZERO:
            values.append(value)
    if not values:
        return None
    return decimal_str(min(values))


def build_multi_order_intent_preview_report(
    *,
    candidates: Iterable[Dict[str, Any]],
    open_orders_state: Optional[Dict[str, Any]] = None,
    positions_state: Optional[Dict[str, Any]] = None,
    policy: Optional[Dict[str, Any]] = None,
    source_paths: Optional[Iterable[str | Path]] = None,
    selected_tests_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    candidate_list = [as_dict(c) for c in candidates if isinstance(c, dict)]
    rules = _policy(policy)
    reservation = build_reservation_preview(
        open_orders_state=open_orders_state,
        positions_state=positions_state,
        quote_available=_quote_available_from_candidates(candidate_list),
        policy=rules,
    )
    intents, near_miss, rejected = select_preview_intents(candidate_list, reservation=reservation, policy=rules)
    warnings: List[str] = []
    blockers: List[str] = []
    if not candidate_list:
        warnings.append("no_local_candidates_found")
    selected_tests = dict(selected_tests_summary or {})
    selected_classification = str(selected_tests.get("selected_tests_classification") or selected_tests.get("classification") or "not_supplied")
    if selected_classification not in {"OK", "not_supplied"}:
        blockers.append("selected_tests_audit_blocker")
    if selected_classification == "not_supplied":
        warnings.append("selected_tests_audit_not_supplied_to_preview")
    if reservation.get("blockers"):
        warnings.extend([str(x) for x in reservation.get("blockers") or []])

    buy_intents = [i for i in intents if i.get("side") == "BUY"]
    sell_intents = [i for i in intents if i.get("side") == "SELL"]
    all_evaluated = intents + near_miss + rejected
    market_previews = [i for i in all_evaluated if i.get("market_order_preview")]
    rejected_reasons: Dict[str, int] = {}
    hard_reasons: Dict[str, int] = {}
    soft_reasons: Dict[str, int] = {}
    for item in rejected:
        for reason in item.get("blockers") or []:
            rejected_reasons[str(reason)] = rejected_reasons.get(str(reason), 0) + 1
        for reason in (item.get("hard_blockers") or []) + (item.get("missing_data_blockers") or []):
            hard_reasons[str(reason)] = hard_reasons.get(str(reason), 0) + 1
        for reason in item.get("soft_blockers") or []:
            soft_reasons[str(reason)] = soft_reasons.get(str(reason), 0) + 1
    for item in near_miss:
        for reason in item.get("soft_blockers") or []:
            soft_reasons[str(reason)] = soft_reasons.get(str(reason), 0) + 1
    hard_rejected = [item for item in rejected if item.get("hard_blockers") or item.get("missing_data_blockers")]
    btc_explanation = None
    for item in all_evaluated:
        if item.get("ticker") == "BTC-USDC":
            btc_explanation = {
                "ticker": item.get("ticker"),
                "status": item.get("status"),
                "setup_family": item.get("setup_family"),
                "confidence": item.get("confidence"),
                "hard_blockers": item.get("hard_blockers") or [],
                "missing_data_blockers": item.get("missing_data_blockers") or [],
                "soft_blockers": item.get("soft_blockers") or [],
                "price": item.get("proposed_price"),
                "volume_pattern_score": item.get("volume_pattern_score"),
                "orderbook_score": item.get("orderbook_score"),
                "reward_risk": as_dict(item.get("expected_value")).get("reward_risk"),
                "edge_score": item.get("edge_score"),
                "promotion_condition": item.get("reason"),
                "explanation": item.get("explanation"),
            }
            break
    risk_summary = {
        "correlation_exposure_policy": "preview_groups_same_quote_usdc_and_limits_new_orders; future integration should add sector/beta clustering before live",
        "max_open_orders_total": rules["max_open_orders_total"],
        "max_quote_per_order": rules["max_quote_per_order"],
        "max_total_buy_quote_reserved": rules["max_total_buy_quote_reserved"],
        "max_new_orders_per_cycle": rules["max_new_orders_per_cycle"],
        "sell_policy": "SELL intents are represented but live execution is disabled and future ACK gated.",
        "market_order_policy": "Market orders are represented but disabled by default and future ACK gated.",
    }
    input_hashes: Dict[str, str] = {}
    for raw in source_paths or []:
        path = Path(raw)
        if path.exists() and path.is_file():
            input_hashes[str(path)] = sha256_file(path)

    status = "preview_ready"
    classification = "OK"
    if blockers:
        status = "blocked_preview"
        classification = "WATCH"
    elif warnings or rejected:
        classification = "WATCH"

    return json_safe(
        {
            "generated_at": now_iso(),
            "phase": D6_MULTI_ORDER_INTENT_PHASE,
            "status": status,
            "classification": classification,
            "preview_only": True,
            "live_order_submit_attempted": False,
            "market_order_submit_attempted": False,
            "sell_order_submit_attempted": False,
            "coinbase_call_attempted": False,
            "state_write_performed": False,
            "strict_approve_trade_route_touched": False,
            "strict_approve_trade_route_remains_required_for_current_live_entry": True,
            "policy": rules,
            "total_candidates": len(candidate_list),
            "total_intents": len(intents),
            "preview_ready_intent_count": len(intents),
            "near_miss_intent_count": len(near_miss),
            "hard_rejected_candidate_count": len(hard_rejected),
            "buy_intents": len(buy_intents),
            "sell_intents_preview": len(sell_intents),
            "market_order_preview_intents": len(market_previews),
            "intents": intents,
            "preview_ready_intents": intents,
            "near_miss_intents": near_miss,
            "hard_rejected_candidates": hard_rejected,
            "top_candidates": intents[:5],
            "top_preview_ready_intents": intents[:5],
            "top_near_miss_intents": near_miss[:5],
            "top_hard_blockers": dict(sorted(hard_reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:10]),
            "top_soft_blockers": dict(sorted(soft_reasons.items(), key=lambda kv: (-kv[1], kv[0]))[:10]),
            "rejected_candidates": rejected,
            "rejected_candidate_count": len(rejected),
            "rejected_reasons": dict(sorted(rejected_reasons.items())),
            "btc_usdc_explanation": btc_explanation,
            "reservation_summary": reservation,
            "risk_summary": risk_summary,
            "blockers": blockers,
            "warnings": warnings,
            "selected_tests_audit": selected_tests or {"selected_tests_classification": "not_supplied"},
            "safety_flags": {
                **d6_metric_safety_flags(),
                "preview_only": True,
                "buy_live_execution_enabled": False,
                "sell_live_execution_enabled": False,
                "market_orders_enabled": False,
                "replication_enabled": False,
                "learning_to_execution_allowed": False,
                "parameter_change_allowed": False,
            },
            "input_hashes": input_hashes,
            "recommended_next_operator_decision": "Review this preview report only; no live integration or order submission until a separate ACK-gated implementation sprint.",
            "next_safe_implementation_step": "Add an ACK-gated dry-run adapter that maps one selected BUY limit intent into the existing strict Phase-C guard without enabling submit.",
        }
    )


def render_multi_order_intent_preview_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# D.6 Multi-Order Intent Preview",
        "",
        "Report-only. No Coinbase calls, no order submits, no market orders, no SELL execution and no trading-state writes.",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('status')}`",
        f"- classification: `{report.get('classification')}`",
        f"- preview_only: `{report.get('preview_only')}`",
        f"- live_order_submit_attempted: `{report.get('live_order_submit_attempted')}`",
        f"- market_order_submit_attempted: `{report.get('market_order_submit_attempted')}`",
        f"- sell_order_submit_attempted: `{report.get('sell_order_submit_attempted')}`",
        f"- total_candidates: `{report.get('total_candidates')}`",
        f"- preview_ready_intent_count: `{report.get('preview_ready_intent_count')}`",
        f"- near_miss_intent_count: `{report.get('near_miss_intent_count')}`",
        f"- hard_rejected_candidate_count: `{report.get('hard_rejected_candidate_count')}`",
        f"- rejected_candidate_count: `{report.get('rejected_candidate_count')}`",
        f"- BUY intents: `{report.get('buy_intents')}`",
        f"- SELL intents preview: `{report.get('sell_intents_preview')}`",
        f"- market-order preview intents: `{report.get('market_order_preview_intents')}`",
        "",
        "## Reservation Summary",
        "",
        "```json",
        json.dumps(report.get("reservation_summary"), indent=2, sort_keys=True),
        "```",
        "",
        "## Top Preview-Ready Intents",
        "",
    ]
    top = report.get("top_preview_ready_intents") or []
    if not top:
        lines.append("- none")
    for item in top:
        lines.append(
            f"- `{item.get('ticker')}` `{item.get('side')}` `{item.get('preferred_order_type')}` "
            f"price `{item.get('proposed_price')}` quote `{item.get('proposed_size_quote')}` "
            f"edge_score `{item.get('edge_score')}` status `{item.get('status')}`"
        )
    lines.extend(["", "## Top Near-Miss Intents", ""])
    near = report.get("top_near_miss_intents") or []
    if not near:
        lines.append("- none")
    for item in near:
        lines.append(
            f"- `{item.get('ticker')}` setup `{item.get('setup_family')}` confidence `{item.get('confidence')}` "
            f"soft `{', '.join(item.get('soft_blockers') or []) or 'none'}` "
            f"watch `{item.get('suggested_watch_level')}` reason `{item.get('reason')}`"
        )
    if report.get("btc_usdc_explanation"):
        lines.extend(["", "## BTC-USDC Explanation", "", "```json", json.dumps(report.get("btc_usdc_explanation"), indent=2, sort_keys=True), "```"])
    lines.extend(["", "## Top Hard Blockers", "", "```json", json.dumps(report.get("top_hard_blockers"), indent=2, sort_keys=True), "```", ""])
    lines.extend(["## Top Soft Blockers", "", "```json", json.dumps(report.get("top_soft_blockers"), indent=2, sort_keys=True), "```", ""])
    lines.extend(["## Rejected Reasons", "", "```json", json.dumps(report.get("rejected_reasons"), indent=2, sort_keys=True), "```", ""])
    lines.extend(
        [
            "## Safety",
            "",
            f"- coinbase_call_attempted: `{report.get('coinbase_call_attempted')}`",
            f"- state_write_performed: `{report.get('state_write_performed')}`",
            f"- strict_approve_trade_route_touched: `{report.get('strict_approve_trade_route_touched')}`",
            f"- recommended_next_operator_decision: `{report.get('recommended_next_operator_decision')}`",
            f"- next_safe_implementation_step: `{report.get('next_safe_implementation_step')}`",
            "",
        ]
    )
    return "\n".join(lines)


__all__ = [
    "D6_MULTI_ORDER_INTENT_PHASE",
    "DEFAULT_POLICY",
    "build_multi_order_intent_preview_report",
    "build_reservation_preview",
    "evaluate_order_intent_candidate",
    "load_json_file",
    "load_recent_analysis_candidates",
    "render_multi_order_intent_preview_markdown",
    "select_preview_intents",
]
