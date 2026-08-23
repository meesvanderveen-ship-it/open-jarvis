from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from bot.order_store import OrderStore
from bot.phase_d3_open_exit_lifecycle_manager import (
    logical_position_id_candidates,
    order_matches_logical_position,
)

ZERO = Decimal("0")
D3_RESERVATION_GOVERNANCE_PHASE = "D3_reservation_governance_read_only"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _position_id(position: Dict[str, Any]) -> str:
    return (
        logical_position_id_candidates(position)[0]
        if logical_position_id_candidates(position)
        else ""
    )


def _bot_manageable_base(position: Dict[str, Any]) -> Decimal:
    for key in ("bot_managed_base", "position_size_base", "base_size", "filled_size_base", "filled_base"):
        value = _to_decimal(position.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _position_base(position: Dict[str, Any]) -> Decimal:
    for key in ("position_size_base", "bot_managed_base", "base_size", "filled_size_base", "filled_base"):
        value = _to_decimal(position.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _base_increment(exchange_rules: Optional[Dict[str, Any]]) -> Decimal:
    rules = _as_dict(exchange_rules)
    for key in ("base_increment", "base_increment_size"):
        value = _to_decimal(rules.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _min_order_quote(exchange_rules: Optional[Dict[str, Any]]) -> Decimal:
    rules = _as_dict(exchange_rules)
    for key in ("quote_min_size", "min_market_funds", "min_order_quote"):
        value = _to_decimal(rules.get(key), "0")
        if value > ZERO:
            return value
    return Decimal("1.00")


def _open_sell_orders_for_position(order_store: OrderStore, *, ticker: str, position_id: str) -> List[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    selected_position = str(position_id or "").strip()
    out: List[Dict[str, Any]] = []
    for order in order_store.open_exit_orders(ticker=selected_ticker or None):
        if str(order.get("side") or "").upper() != "SELL":
            continue
        if selected_position and not order_matches_logical_position(
            order,
            linked_position_id=selected_position,
        ):
            continue
        out.append(dict(order))
    return out


def build_phase_d3_reservation_governance_snapshot(
    *,
    ticker: str,
    position: Optional[Dict[str, Any]],
    order_store: Optional[OrderStore] = None,
    plan: Optional[Dict[str, Any]] = None,
    exchange_rules: Optional[Dict[str, Any]] = None,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker or (position or {}).get("ticker"))
    pos = _as_dict(position)
    store = order_store or OrderStore()
    position_present = bool(pos) and str(pos.get("status") or "").strip().lower() in {"open", "active"}
    position_id = _position_id(pos)
    total_base = _position_base(pos) if position_present else ZERO
    bot_manageable_base = _bot_manageable_base(pos) if position_present else ZERO
    open_exit_orders = _open_sell_orders_for_position(store, ticker=selected, position_id=position_id)

    reserved_base = ZERO
    labels: List[str] = []
    actions: List[str] = []
    for order in open_exit_orders:
        reserved_base += max(ZERO, _to_decimal(order.get("remaining_size") or order.get("size_base"), "0"))
        label = str(order.get("d3_exit_label") or "").strip().upper()
        action = str(order.get("execution_action") or "").strip().lower()
        if label:
            labels.append(label)
        if action:
            actions.append(action)

    available_base = max(ZERO, bot_manageable_base - reserved_base)
    available_plus_reserved_base = available_base + reserved_base
    duplicate_labels_detected = len(set(labels)) != len(labels) if labels else False
    duplicate_actions_detected = len(set(actions)) != len(actions) if actions else False

    increment = _base_increment(exchange_rules)
    min_quote = _min_order_quote(exchange_rules)
    min_size_ready = False
    warnings: List[str] = []
    blockers: List[str] = []

    if not position_present:
        blockers.append("no_manageable_open_position")
    if not position_id:
        blockers.append("position_id_missing")
    if total_base <= ZERO:
        blockers.append("position_base_missing_or_zero")
    if bot_manageable_base <= ZERO:
        blockers.append("bot_manageable_base_missing_or_zero")
    if available_base <= ZERO:
        blockers.append("no_available_base_after_existing_exit_reservations")
    if duplicate_labels_detected:
        blockers.append("duplicate_exit_labels_open")
    if duplicate_actions_detected:
        blockers.append("duplicate_exit_actions_open")

    candidate_base = available_base
    if candidate_base > ZERO and increment > ZERO:
        units = (candidate_base / increment).to_integral_value()
        candidate_base = units * increment if units > 0 else ZERO
        if candidate_base <= ZERO:
            blockers.append("available_base_below_base_increment")

    if candidate_base > ZERO:
        candidate_price = ZERO
        plan_dict = _as_dict(plan)
        exits = plan_dict.get("exits")
        if isinstance(exits, list):
            for raw in exits:
                row = _as_dict(raw)
                if bool(row.get("trailing_stop")):
                    continue
                price = _to_decimal(row.get("limit_price"), "0")
                if price > ZERO:
                    candidate_price = price
                    break
        if candidate_price <= ZERO:
            warnings.append("no_non_trailing_limit_price_available_for_min_quote_check")
            blockers.append("min_quote_readiness_unclear")
        else:
            min_size_ready = candidate_base * candidate_price >= min_quote
            if not min_size_ready:
                blockers.append("available_base_below_min_order_quote")
    else:
        blockers.append("min_quote_readiness_unavailable_without_positive_available_base")

    coherent = not blockers
    return _json_safe({
        "phase": D3_RESERVATION_GOVERNANCE_PHASE,
        "generated_at": generated_at or _now_iso(),
        "ticker": selected,
        "position_present": position_present,
        "position_id": position_id,
        "total_base": str(total_base),
        "bot_manageable_base": str(bot_manageable_base),
        "reserved_base_open_exit_orders": str(reserved_base),
        "available_base_after_reservations": str(available_base),
        "available_plus_reserved_base": str(available_plus_reserved_base),
        "available_reserved_matches_bot_manageable_base": bool(available_plus_reserved_base == bot_manageable_base),
        "open_exit_orders_count": len(open_exit_orders),
        "open_exit_labels": labels,
        "open_exit_actions": actions,
        "duplicate_labels_detected": duplicate_labels_detected,
        "duplicate_actions_detected": duplicate_actions_detected,
        "base_increment": str(increment),
        "min_order_quote": str(min_quote),
        "min_size_ready": bool(min_size_ready),
        "future_controlled_sell_pilot_coherent": bool(coherent),
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "fail_closed_recommendation": True,
        "safety_policy": {
            "read_only_diagnostic_only": True,
            "does_not_submit": True,
            "does_not_arm_exits": True,
            "does_not_mutate_state": True,
            "does_not_write_persistent_ledger": True,
            "never_authorizes_live_submit": True,
        },
    })


__all__ = [
    "D3_RESERVATION_GOVERNANCE_PHASE",
    "build_phase_d3_reservation_governance_snapshot",
]
