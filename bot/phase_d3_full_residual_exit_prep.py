from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Dict, Optional

from bot.order_store import OrderStore
from bot.phase_d3_controlled_live_exits import (
    D3_ACK,
    D3_PHASE,
    assess_phase_d3_exit_readiness,
    count_phase_d3_live_exit_orders,
)
from bot.phase_d3_reservation_governance import build_phase_d3_reservation_governance_snapshot
from bot.state_store import StateStore

PHASE_D3_FULL_RESIDUAL_EXIT_PREP = "D3_full_residual_exit_final_prep"
FUTURE_RESIDUAL_EXIT_ACK = "I_UNDERSTAND_AND_APPROVE_CONTROLLED_D3_D4_RESIDUAL_EXIT_SUBMIT_FOR_BTC_USDC"
ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


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


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _quantize_down(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= ZERO:
        return value
    try:
        units = (value / increment).to_integral_value(rounding=ROUND_DOWN)
        return units * increment
    except Exception:
        return value


def _position_base(position: Dict[str, Any]) -> Decimal:
    for key in ("bot_managed_base", "position_size_base", "base_size"):
        value = _to_decimal(position.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _position_id(position: Dict[str, Any]) -> str:
    return str(position.get("order_id") or position.get("position_id") or "").strip()


def _open_exit_reserved_base(orders: OrderStore, *, ticker: str) -> Decimal:
    total = ZERO
    for order in orders.open_exit_orders(ticker=ticker):
        total += max(ZERO, _to_decimal(order.get("remaining_size") or order.get("size_base"), "0"))
    return total


def build_phase_d3_full_residual_exit_prep_report(
    *,
    cfg: Any,
    ticker: str,
    limit_price: Any,
    state_store: Optional[StateStore] = None,
    order_store: Optional[OrderStore] = None,
    base_increment: Any = "0.00000001",
    base_min_size: Any = "0.00000001",
    quote_min_size: Any = "1",
    price_increment: Any = "0.01",
    live_base_available: Any = None,
    route_label: str = "TP_CLOSE",
) -> Dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    state = state_store or StateStore()
    orders = order_store or OrderStore()
    position = state.get_position(ticker) or {}
    limit = _to_decimal(limit_price, "0")
    increment = _to_decimal(base_increment, "0")
    min_base = _to_decimal(base_min_size, "0")
    min_quote = _to_decimal(quote_min_size, "0")
    px_increment = _to_decimal(price_increment, "0")
    live_available = _to_decimal(live_base_available, "-1") if live_base_available is not None else None
    raw_full_base = _position_base(position)
    rounded_full_base = _quantize_down(raw_full_base, increment)
    estimated_quote = rounded_full_base * limit if rounded_full_base > ZERO and limit > ZERO else ZERO
    position_id = _position_id(position)
    reserved_base = _open_exit_reserved_base(orders, ticker=ticker)
    available_after_reservations = max(ZERO, raw_full_base - reserved_base)

    candidate_plan = {
        "status": "position_executor_plan_ready_no_live_exit_submit",
        "ticker": ticker,
        "position_id": position_id,
        "plan_id": "read_only_full_residual_final_prep",
    }
    exit_intent = {
        "generated_at": _now_iso(),
        "phase": D3_PHASE,
        "intent_id": "read_only_full_residual_exit_candidate",
        "client_order_id": "READ_ONLY_FULL_RESIDUAL_EXIT_CANDIDATE_NOT_FOR_SUBMIT",
        "ticker": ticker,
        "position_id": position_id,
        "side": "SELL",
        "execution_action": "place_limit_sell",
        "label": str(route_label or "TP_CLOSE").strip().upper(),
        "size_base": str(rounded_full_base),
        "raw_limit_price": str(limit),
        "limit_price": str(limit),
        "estimated_quote_value": str(estimated_quote),
        "price_increment_used": str(px_increment),
        "price_precision_context": "read_only_operator_supplied_limit_price",
        "requested_base_before_clamp": str(raw_full_base),
        "position_base": str(raw_full_base),
        "reserved_base_existing_exit_orders": str(reserved_base),
        "available_base_after_reservations": str(available_after_reservations),
        "reduce_only_local": True,
        "post_only": bool(getattr(cfg, "phase_d3_exit_order_post_only", True)),
        "blockers": [],
        "warnings": ["read_only_candidate_not_a_live_payload"],
        "source_plan_id": "read_only_full_residual_final_prep",
        "source_plan_status": "position_executor_plan_ready_no_live_exit_submit",
    }
    readiness = assess_phase_d3_exit_readiness(
        cfg=cfg,
        position=position,
        plan=candidate_plan,
        exit_intent=exit_intent,
        order_store=orders,
        human_ack="",
        submit_live=False,
    )
    governance = build_phase_d3_reservation_governance_snapshot(
        ticker=ticker,
        position=position,
        order_store=orders,
        plan=None,
        exchange_rules={
            "base_increment": str(increment),
            "base_min_size": str(min_base),
            "quote_min_size": str(min_quote),
            "price_increment": str(px_increment),
        },
    )

    blockers: list[str] = []
    warnings: list[str] = []
    if not position:
        blockers.append("position_missing")
    if raw_full_base <= ZERO:
        blockers.append("residual_base_nonpositive")
    if rounded_full_base <= ZERO:
        blockers.append("rounded_sell_base_nonpositive")
    if min_base > ZERO and rounded_full_base < min_base:
        blockers.append("rounded_sell_base_below_base_min_size")
    if limit <= ZERO:
        blockers.append("limit_price_missing_or_nonpositive")
    if min_quote > ZERO and estimated_quote < min_quote:
        blockers.append("estimated_quote_below_quote_min_size")
    if rounded_full_base > available_after_reservations:
        blockers.append("rounded_sell_base_exceeds_available_after_reservations")
    if live_available is not None:
        if live_available < ZERO:
            warnings.append("live_base_available_not_provided")
        elif live_available < rounded_full_base:
            blockers.append("live_base_available_below_rounded_sell_base")
    else:
        warnings.append("live_base_available_not_provided")
    if not readiness.get("ready"):
        blockers.append("d3_readiness_not_green_for_full_residual_candidate")
    if str(route_label or "").strip().upper() != "TP_CLOSE":
        warnings.append("non_default_full_residual_route_label")
    if px_increment > ZERO and limit != _quantize_down(limit, px_increment):
        warnings.append("limit_price_not_aligned_to_price_increment")
    if raw_full_base != rounded_full_base:
        warnings.append("sell_base_rounded_down_to_base_increment")

    blockers = sorted(set(blockers + list(readiness.get("blockers") or [])))
    warnings = sorted(set(warnings + list(readiness.get("warnings") or [])))
    ready_for_future_operator_review = not blockers

    return _json_safe({
        "phase": PHASE_D3_FULL_RESIDUAL_EXIT_PREP,
        "generated_at": _now_iso(),
        "ticker": ticker,
        "status": "d3_full_residual_exit_final_prep_ready" if ready_for_future_operator_review else "d3_full_residual_exit_final_prep_blocked",
        "route": "single_full_residual_exit",
        "route_label": str(route_label or "TP_CLOSE").strip().upper(),
        "position_present": bool(position),
        "position_id": position_id,
        "position_status": str(position.get("status") or ""),
        "raw_full_residual_base": str(raw_full_base),
        "rounded_sell_base": str(rounded_full_base),
        "base_rounding_delta": str(raw_full_base - rounded_full_base),
        "limit_price": str(limit),
        "estimated_quote_value": str(estimated_quote),
        "product_rules": {
            "base_increment": str(increment),
            "base_min_size": str(min_base),
            "quote_min_size": str(min_quote),
            "price_increment": str(px_increment),
        },
        "min_size_checks": {
            "base_above_min": bool(rounded_full_base >= min_base > ZERO) if min_base > ZERO else bool(rounded_full_base > ZERO),
            "quote_above_min": bool(estimated_quote >= min_quote > ZERO) if min_quote > ZERO else bool(estimated_quote > ZERO),
            "rounding_zeroed_size": bool(raw_full_base > ZERO and rounded_full_base <= ZERO),
        },
        "local_governance": {
            "open_d3_exit_orders": count_phase_d3_live_exit_orders(orders),
            "reserved_base_open_exit_orders": str(reserved_base),
            "available_base_after_reservations": str(available_after_reservations),
            "duplicate_exit_order_for_position_action": bool(
                orders.has_duplicate_exit_order(
                    ticker=ticker,
                    execution_action="place_limit_sell",
                    linked_position_id=position_id,
                )
            ),
            "reservation_governance": governance,
        },
        "live_base_available": str(live_available) if live_available is not None and live_available >= ZERO else None,
        "live_base_sufficient": bool(live_available is not None and live_available >= rounded_full_base > ZERO),
        "readiness": readiness,
        "future_operator_acceptance_required": {
            "accepts_single_full_residual_route": True,
            "accepts_deviation_from_split_first_d2_d3_route": True,
            "accepts_no_runner_or_tp2_left_after_full_exit": True,
            "accepts_exact_limit_price": str(limit),
            "accepts_exact_sell_base_after_rounding": str(rounded_full_base),
        },
        "future_live_submit_ack_required": FUTURE_RESIDUAL_EXIT_ACK,
        "underlying_d3_ack_required_by_submit_function": D3_ACK,
        "safety_policy": {
            "read_only_report_only": True,
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_replace": True,
            "does_not_reprice": True,
            "does_not_mutate_state": True,
            "does_not_call_coinbase": True,
            "not_an_executable_order_payload": True,
            "future_live_submit_requires_new_ack_and_submit_path_review": True,
        },
        "blockers": blockers,
        "warnings": warnings,
    })


__all__ = [
    "FUTURE_RESIDUAL_EXIT_ACK",
    "PHASE_D3_FULL_RESIDUAL_EXIT_PREP",
    "build_phase_d3_full_residual_exit_prep_report",
]
