from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Dict, Iterable, List, Optional


D4_TRAILING_PREVIEW_PHASE = "D4_trailing_preview"
D4_TRAILING_PREVIEW_REQUIRED_ACK = "I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT"
ZERO = Decimal("0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


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


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _quantize_up(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= ZERO:
        return value
    units = (value / increment).to_integral_value(rounding=ROUND_CEILING)
    return units * increment


def _find_open_d3_exit_orders(
    orders: Iterable[Dict[str, Any]],
    *,
    ticker: str,
    linked_position_id: str,
) -> List[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    selected_position = str(linked_position_id or "").strip()
    out: List[Dict[str, Any]] = []
    for order in orders:
        if _normalize_ticker(order.get("ticker")) != selected_ticker:
            continue
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if str(order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
            continue
        if str(order.get("status") or "").strip().lower() not in {"planned", "pending", "submitted", "open", "partially_filled", "cancel_pending", "replace_pending"}:
            continue
        if selected_position and str(order.get("linked_position_id") or "").strip() != selected_position:
            continue
        out.append(dict(order))
    return out


def _find_current_order(
    orders: Iterable[Dict[str, Any]],
    *,
    ticker: str,
    linked_position_id: str,
    current_order: Optional[Dict[str, Any]],
    client_order_id: str,
    exchange_order_id: str,
) -> Dict[str, Any]:
    if isinstance(current_order, dict) and current_order:
        return dict(current_order)
    selected_ticker = _normalize_ticker(ticker)
    selected_client = str(client_order_id or "").strip()
    selected_exchange = str(exchange_order_id or "").strip()
    selected_position = str(linked_position_id or "").strip()
    for order in orders:
        if selected_ticker and _normalize_ticker(order.get("ticker")) != selected_ticker:
            continue
        if selected_client and str(order.get("client_order_id") or "").strip() == selected_client:
            return dict(order)
        order_exchange = str(order.get("exchange_order_id") or order.get("order_id") or "").strip()
        if selected_exchange and order_exchange == selected_exchange:
            return dict(order)
        if selected_position and str(order.get("linked_position_id") or "").strip() == selected_position:
            return dict(order)
    return {}


def build_phase_d4_trailing_preview_report(
    *,
    ticker: str,
    linked_position_id: str,
    current_order: Optional[Dict[str, Any]] = None,
    position: Optional[Dict[str, Any]] = None,
    market_snapshot: Optional[Dict[str, Any]] = None,
    product_rules: Optional[Dict[str, Any]] = None,
    policy: Optional[Dict[str, Any]] = None,
    open_orders: Optional[Iterable[Dict[str, Any]]] = None,
    client_order_id: str = "",
    exchange_order_id: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    selected_position = str(linked_position_id or "").strip()
    now_dt = now or _now()
    order_candidates = list(open_orders or [])
    order = _find_current_order(
        order_candidates,
        ticker=selected_ticker,
        linked_position_id=selected_position,
        current_order=current_order,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
    )
    position = dict(position or {})
    market = dict(market_snapshot or {})
    rules = dict(product_rules or {})
    policy = dict(policy or {})

    client_id = str(order.get("client_order_id") or client_order_id or "").strip()
    exchange_id = str(order.get("exchange_order_id") or order.get("order_id") or exchange_order_id or "").strip()
    current_order_id = client_id or exchange_id
    current_exit_price = _to_decimal(order.get("limit_price"), "0")
    current_size = _to_decimal(order.get("remaining_size") or order.get("size_base"), "0")
    filled_base = _to_decimal(order.get("filled_base") or order.get("filled_size"), "0")
    fill_count = _to_int(order.get("fill_count"), 0)
    position_size_base = _to_decimal(position.get("position_size_base"), "0")
    reserved_base = _to_decimal(position.get("reserved_base_open_exit_orders"), "0")
    best_bid = _to_decimal(market.get("best_bid"), "0")
    best_ask = _to_decimal(market.get("best_ask"), "0")
    mid_price = _to_decimal(market.get("mid_price"), "0")
    price_increment = _to_decimal(rules.get("price_increment"), "0.01")
    base_increment = _to_decimal(rules.get("base_increment"), "0.00000001")
    min_order_quote = _to_decimal(rules.get("min_order_quote"), "0")
    activation_price = _to_decimal(policy.get("activation_price"), "0")
    activation_pct = _to_decimal(policy.get("activation_pct"), "0")
    activation_reference = _to_decimal(policy.get("activation_reference_price") or current_exit_price, "0")
    trailing_distance_pct = _to_decimal(policy.get("trailing_distance_pct"), "0")
    refresh_tolerance_pct = _to_decimal(policy.get("refresh_tolerance_pct"), "0")
    stale_book_seconds = _to_decimal(policy.get("stale_book_seconds"), "0")
    cooldown_seconds = _to_decimal(policy.get("cooldown_seconds"), "0")
    prior_peak = _to_decimal(policy.get("prior_peak_price"), "0")
    candidate_override = _to_decimal(policy.get("candidate_price_override"), "0")
    cooldown_until = _parse_time(policy.get("cooldown_until"))
    last_candidate_at = _parse_time(policy.get("last_candidate_at") or policy.get("last_cancel_replace_at"))
    market_time = _parse_time(market.get("timestamp"))

    blockers: List[str] = []
    warnings: List[str] = []
    duplicate_open_exits = _find_open_d3_exit_orders(
        order_candidates,
        ticker=selected_ticker,
        linked_position_id=selected_position,
    )

    report: Dict[str, Any] = {
        "generated_at": now_dt.isoformat(),
        "phase": D4_TRAILING_PREVIEW_PHASE,
        "status": "d4_trailing_preview_blocked",
        "ticker": selected_ticker,
        "linked_position_id": selected_position,
        "current_order_id": current_order_id,
        "client_order_id": client_id,
        "exchange_order_id": exchange_id,
        "current_exit_price": str(current_exit_price),
        "current_market_mid": str(mid_price),
        "activation_state": "inactive",
        "peak_reference_price": "0",
        "trailing_distance": "0",
        "trailing_stop_price": "0",
        "proposed_replacement_price": "",
        "proposed_replacement_quote": "0",
        "proposed_action": "blocked",
        "reason": "blocked_review_required",
        "blockers": blockers,
        "warnings": warnings,
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "cancel_replace_allowed": False,
        "requires_future_ack": False,
        "required_future_ack": D4_TRAILING_PREVIEW_REQUIRED_ACK,
        "open_d3_exit_count": len(duplicate_open_exits),
        "duplicate_open_d3_exit_detected": False,
        "oversell_detected": False,
        "post_only_feasible": False,
        "market_snapshot_stale": False,
        "cooldown_active": False,
        "policy": _json_safe(policy),
        "product_rules": _json_safe(rules),
        "market_snapshot": _json_safe(market),
    }

    if not order:
        blockers.append("open_d3_exit_order_not_found")
    if len(duplicate_open_exits) > 1:
        blockers.append("duplicate_open_d3_exit_orders_for_position")
        report["duplicate_open_d3_exit_detected"] = True
    if selected_position and str(order.get("linked_position_id") or "").strip() not in {"", selected_position}:
        blockers.append("linked_position_id_mismatch")
    if str(order.get("side") or "").strip().upper() not in {"", "SELL"}:
        blockers.append("current_order_not_sell")
    if str(order.get("status") or "").strip().lower() not in {"submitted", "open"}:
        blockers.append("current_order_not_open_or_submitted")
    if filled_base > ZERO or fill_count > 0:
        blockers.append("current_order_has_fills_use_d3_lifecycle_first")
    if current_size <= ZERO:
        blockers.append("current_order_remaining_size_missing")
    if reserved_base < current_size:
        blockers.append("reserved_base_less_than_open_exit_size")
        report["oversell_detected"] = True
    if base_increment > ZERO and current_size < base_increment:
        blockers.append("current_order_below_base_increment")
    if current_exit_price <= ZERO:
        blockers.append("current_exit_price_missing")
    if best_bid <= ZERO or best_ask <= ZERO or mid_price <= ZERO:
        blockers.append("market_snapshot_missing_or_invalid")
    if market_time is None:
        blockers.append("market_snapshot_timestamp_missing_or_invalid")
    elif stale_book_seconds > ZERO:
        age = max(ZERO, Decimal(str((now_dt - market_time).total_seconds())))
        report["market_snapshot_age_seconds"] = str(age)
        if age > stale_book_seconds:
            blockers.append("market_snapshot_stale")
            report["market_snapshot_stale"] = True
    if cooldown_until and now_dt < cooldown_until:
        blockers.append("cooldown_active")
        report["cooldown_active"] = True
    elif last_candidate_at and cooldown_seconds > ZERO:
        elapsed = Decimal(str((now_dt - last_candidate_at).total_seconds()))
        if elapsed < cooldown_seconds:
            blockers.append("cooldown_active")
            report["cooldown_active"] = True

    if activation_price <= ZERO and activation_pct > ZERO and activation_reference > ZERO:
        activation_price = activation_reference * (Decimal("1") + activation_pct)
    if activation_price <= ZERO:
        blockers.append("activation_price_or_pct_required")
    if trailing_distance_pct <= ZERO:
        blockers.append("trailing_distance_pct_required")

    peak_reference = max(prior_peak, mid_price)
    trailing_distance = peak_reference * trailing_distance_pct if peak_reference > ZERO else ZERO
    trailing_stop_price = peak_reference - trailing_distance if peak_reference > ZERO else ZERO
    report["activation_price"] = str(activation_price)
    report["peak_reference_price"] = str(peak_reference)
    report["trailing_distance"] = str(trailing_distance)
    report["trailing_stop_price"] = str(trailing_stop_price)

    if blockers:
        report["status"] = "d4_trailing_preview_blocked"
        report["proposed_action"] = "blocked"
        report["reason"] = blockers[0]
        return _json_safe(report)

    if peak_reference < activation_price:
        report["status"] = "d4_trailing_preview_keep_open"
        report["activation_state"] = "inactive"
        report["proposed_action"] = "keep_open"
        report["reason"] = "price_below_activation"
        return _json_safe(report)

    report["activation_state"] = "active"
    if mid_price > trailing_stop_price:
        report["status"] = "d4_trailing_preview_keep_open"
        report["proposed_action"] = "keep_open"
        report["reason"] = "trailing_stop_not_triggered"
        return _json_safe(report)

    post_only_floor = best_ask + price_increment if price_increment > ZERO else best_ask
    raw_candidate = candidate_override if candidate_override > ZERO else max(trailing_stop_price, post_only_floor)
    candidate = _quantize_up(raw_candidate, price_increment)
    candidate_quote = candidate * current_size
    report["proposed_replacement_price"] = str(candidate)
    report["proposed_replacement_quote"] = str(candidate_quote)
    report["post_only_feasible"] = candidate > best_bid

    if candidate <= best_bid:
        blockers.append("candidate_crosses_book_post_only_unsafe")
    if candidate_quote < min_order_quote:
        blockers.append("candidate_below_min_order_quote")
    if candidate <= ZERO:
        blockers.append("candidate_price_invalid")

    if blockers:
        report["status"] = "d4_trailing_preview_blocked"
        report["proposed_action"] = "blocked"
        report["reason"] = blockers[0]
        return _json_safe(report)

    if current_exit_price > ZERO and refresh_tolerance_pct > ZERO:
        drift_pct = abs(candidate - current_exit_price) / current_exit_price
        report["refresh_drift_pct"] = str(drift_pct)
        if drift_pct <= refresh_tolerance_pct:
            report["status"] = "d4_trailing_preview_keep_open"
            report["proposed_action"] = "keep_open"
            report["reason"] = "candidate_inside_refresh_tolerance"
            warnings.append("replacement_candidate_inside_refresh_tolerance")
            return _json_safe(report)

    report["status"] = "d4_trailing_preview_candidate_ready"
    report["proposed_action"] = "preview_reprice_candidate"
    report["reason"] = "trailing_stop_triggered_candidate_preview_only"
    report["requires_future_ack"] = True
    report["cancel_replace_allowed"] = False
    warnings.append("preview_only_no_cancel_replace_submit")
    return _json_safe(report)


def build_phase_d4_trailing_market_path_preview(
    *,
    ticker: str,
    linked_position_id: str,
    market_path: Iterable[Dict[str, Any]],
    current_order: Optional[Dict[str, Any]] = None,
    position: Optional[Dict[str, Any]] = None,
    product_rules: Optional[Dict[str, Any]] = None,
    policy: Optional[Dict[str, Any]] = None,
    open_orders: Optional[Iterable[Dict[str, Any]]] = None,
    client_order_id: str = "",
    exchange_order_id: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    base_policy = dict(policy or {})
    reports: List[Dict[str, Any]] = []
    peak = _to_decimal(base_policy.get("prior_peak_price"), "0")
    for snapshot in market_path:
        step_policy = dict(base_policy)
        if peak > ZERO:
            step_policy["prior_peak_price"] = str(peak)
        report = build_phase_d4_trailing_preview_report(
            ticker=ticker,
            linked_position_id=linked_position_id,
            current_order=current_order,
            position=position,
            market_snapshot=snapshot,
            product_rules=product_rules,
            policy=step_policy,
            open_orders=open_orders,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            now=now,
        )
        reports.append(report)
        peak = max(peak, _to_decimal(report.get("peak_reference_price"), "0"))
    final = reports[-1] if reports else {}
    return _json_safe({
        "generated_at": (now or _now()).isoformat(),
        "phase": f"{D4_TRAILING_PREVIEW_PHASE}_market_path",
        "ticker": _normalize_ticker(ticker),
        "linked_position_id": str(linked_position_id or "").strip(),
        "path_length": len(reports),
        "final_status": str(final.get("status") or "d4_trailing_preview_blocked"),
        "final_proposed_action": str(final.get("proposed_action") or "blocked"),
        "final_reason": str(final.get("reason") or "market_path_empty"),
        "final_peak_reference_price": str(final.get("peak_reference_price") or "0"),
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "cancel_replace_allowed": False,
        "reports": reports,
    })


__all__ = [
    "D4_TRAILING_PREVIEW_PHASE",
    "D4_TRAILING_PREVIEW_REQUIRED_ACK",
    "build_phase_d4_trailing_market_path_preview",
    "build_phase_d4_trailing_preview_report",
]
