from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional


D5_EXECUTION_METRICS_PHASE = "D5_execution_metrics_scaffold"
D5_REQUIRED_FUTURE_EXECUTION_GATE = "D5_LEARNING_TO_EXECUTION_REQUIRES_SEPARATE_OPERATOR_APPROVAL_AND_ACK"
ZERO = Decimal("0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _seconds_between(start: Any, end: Any) -> str:
    start_dt = _parse_time(start)
    end_dt = _parse_time(end)
    if not start_dt or not end_dt:
        return ""
    return str(max(ZERO, Decimal(str((end_dt - start_dt).total_seconds()))))


def _pct(numerator: Decimal, denominator: Decimal) -> str:
    if denominator <= ZERO:
        return ""
    return str(numerator / denominator)


def _target_distance_band(distance_abs_pct: Decimal) -> str:
    if distance_abs_pct <= Decimal("0.01"):
        return "near_target"
    if distance_abs_pct <= Decimal("0.03"):
        return "approaching_target"
    return "far_from_target"


def _no_fill_recommendation_label(*, band: str, stale_order_age: str, lifecycle_status: str) -> str:
    if lifecycle_status != "open":
        return "not_applicable"
    stale_seconds = _to_decimal(stale_order_age, "0")
    if band == "near_target":
        return "monitor_later"
    if band == "approaching_target":
        return "monitor_later"
    if stale_seconds >= Decimal("21600"):
        return "consider_reprice_later"
    return "wait"


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    aliases = {
        "open": "open",
        "submitted": "open",
        "partially_filled": "partial",
        "partial": "partial",
        "filled": "filled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
    }
    return aliases.get(status, status or "unknown")


def _terminal_time(event: Dict[str, Any], fills: Dict[str, Any]) -> str:
    for key in ("terminal_at", "closed_at", "filled_at", "cancelled_at", "expired_at", "rejected_at"):
        value = event.get(key) or fills.get(key)
        if value:
            return str(value)
    return ""


def build_phase_d5_execution_metrics_report(
    *,
    lifecycle_event: Dict[str, Any],
    plan_fields: Optional[Dict[str, Any]] = None,
    market_refs: Optional[Dict[str, Any]] = None,
    fills: Optional[Dict[str, Any]] = None,
    d4_decision: Optional[Dict[str, Any]] = None,
    coinbase_client: Any = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    event = dict(lifecycle_event or {})
    plan = dict(plan_fields or {})
    market = dict(market_refs or {})
    fill = dict(fills or {})
    d4 = dict(d4_decision or {})
    now_dt = now or _now()
    warnings = []
    blockers = []

    if coinbase_client is not None:
        warnings.append("coinbase_client_ignored_analysis_only")

    lifecycle_status = _normalize_status(
        event.get("lifecycle_status")
        or event.get("normalized_status")
        or event.get("status")
    )
    filled_base = _to_decimal(fill.get("filled_base") or event.get("filled_base"), "0")
    filled_quote = _to_decimal(fill.get("filled_quote") or event.get("filled_quote"), "0")
    avg_fill_price = _to_decimal(fill.get("avg_fill_price") or event.get("avg_fill_price"), "0")
    fees = _to_decimal(fill.get("fees") or event.get("fees"), "0")
    fill_count = _to_int(fill.get("fill_count") or event.get("fill_count"), 0)
    planned_exit_price = _to_decimal(plan.get("planned_exit_price") or event.get("planned_exit_price"), "0")
    planned_entry_price = _to_decimal(plan.get("planned_entry_price") or event.get("planned_entry_price"), "0")
    planned_size_base = _to_decimal(plan.get("planned_size_base") or event.get("planned_size_base"), "0")
    decision_mid = _to_decimal(market.get("decision_mid"), "0")
    decision_best_bid = _to_decimal(market.get("decision_best_bid"), "0")
    decision_best_ask = _to_decimal(market.get("decision_best_ask"), "0")
    terminal_at = _terminal_time(event, fill)
    submitted_at = event.get("submitted_at") or event.get("order_created_at")
    first_seen_open_at = event.get("first_seen_open_at") or submitted_at
    first_fill_at = fill.get("first_fill_at") or event.get("first_fill_at")
    final_fill_at = fill.get("final_fill_at") or event.get("final_fill_at") or terminal_at

    realized_exit_price = avg_fill_price
    if realized_exit_price <= ZERO and filled_base > ZERO:
        realized_exit_price = filled_quote / filled_base

    if decision_mid <= ZERO:
        warnings.append("market_decision_mid_missing_slippage_partial")
    if decision_best_bid <= ZERO:
        warnings.append("market_decision_best_bid_missing_slippage_partial")

    fill_latency = _seconds_between(submitted_at, first_fill_at)
    stale_order_age = _seconds_between(first_seen_open_at, terminal_at or now_dt)
    no_fill_duration = ""
    if filled_base <= ZERO:
        no_fill_duration = _seconds_between(first_seen_open_at, terminal_at or now_dt)

    is_terminal = lifecycle_status in {"filled", "cancelled", "expired", "rejected"}
    is_complete = lifecycle_status == "filled" or (is_terminal and filled_base == ZERO)
    is_training_eligible = False

    if lifecycle_status == "open" and filled_base <= ZERO:
        fill_quality = "no_fill_open"
    elif lifecycle_status == "partial":
        fill_quality = "partial"
    elif lifecycle_status == "filled":
        if planned_exit_price > ZERO and realized_exit_price >= planned_exit_price:
            fill_quality = "filled_good"
        else:
            fill_quality = "filled_bad"
    elif lifecycle_status in {"cancelled", "expired", "rejected"} and filled_base <= ZERO:
        fill_quality = "terminal_no_fill"
    else:
        fill_quality = "incomplete_not_trainable"

    realized_vs_planned = ""
    if realized_exit_price > ZERO and planned_exit_price > ZERO:
        realized_vs_planned = _pct(realized_exit_price - planned_exit_price, planned_exit_price)

    slippage_mid = ""
    if realized_exit_price > ZERO and decision_mid > ZERO:
        slippage_mid = _pct(realized_exit_price - decision_mid, decision_mid)

    slippage_bid_or_ask = ""
    if realized_exit_price > ZERO and decision_best_bid > ZERO:
        slippage_bid_or_ask = _pct(realized_exit_price - decision_best_bid, decision_best_bid)

    target_distance_abs = ""
    target_distance_pct = ""
    target_distance_abs_pct = ZERO
    target_distance_band = ""
    if planned_exit_price > ZERO and decision_mid > ZERO:
        target_distance = planned_exit_price - decision_mid
        target_distance_abs = str(abs(target_distance))
        target_distance_pct = _pct(target_distance, planned_exit_price)
        target_distance_abs_pct = abs(target_distance) / planned_exit_price
        target_distance_band = _target_distance_band(target_distance_abs_pct)

    fee_bps = ""
    if filled_quote > ZERO and fees >= ZERO:
        fee_bps = str((fees / filled_quote) * Decimal("10000"))

    if lifecycle_status == "open":
        blockers.append("open_lifecycle_not_training_eligible")
    if lifecycle_status == "partial":
        blockers.append("partial_lifecycle_without_terminal_not_training_eligible")

    report = {
        "generated_at": now_dt.isoformat(),
        "phase": D5_EXECUTION_METRICS_PHASE,
        "status": "d5_execution_metrics_report_ready",
        "lifecycle_status": lifecycle_status,
        "is_complete_lifecycle_event": is_complete,
        "is_training_eligible": is_training_eligible,
        "fill_latency_seconds": fill_latency,
        "no_fill_duration_seconds": no_fill_duration,
        "realized_exit_price": str(realized_exit_price) if realized_exit_price > ZERO else "",
        "planned_exit_price": str(planned_exit_price) if planned_exit_price > ZERO else "",
        "planned_entry_price": str(planned_entry_price) if planned_entry_price > ZERO else "",
        "planned_size_base": str(planned_size_base) if planned_size_base > ZERO else "",
        "realized_vs_planned_edge_pct": realized_vs_planned,
        "slippage_vs_decision_mid_pct": slippage_mid,
        "slippage_vs_best_bid_or_ask_pct": slippage_bid_or_ask,
        "target_distance_abs": target_distance_abs,
        "target_distance_pct": target_distance_pct,
        "target_distance_band": target_distance_band,
        "fee_quote": str(fees),
        "fee_bps_estimate": fee_bps,
        "filled_base": str(filled_base),
        "filled_quote": str(filled_quote),
        "avg_fill_price": str(avg_fill_price) if avg_fill_price > ZERO else "",
        "fill_count": fill_count,
        "fill_quality_label": fill_quality,
        "no_fill_reason_label": str(event.get("no_fill_reason_label") or ""),
        "stale_order_age_seconds": stale_order_age,
        "no_fill_recommendation_label": _no_fill_recommendation_label(
            band=target_distance_band,
            stale_order_age=stale_order_age,
            lifecycle_status=lifecycle_status,
        ),
        "cancel_replace_outcome": str(d4.get("cancel_replace_outcome") or d4.get("proposed_action") or ""),
        "learning_to_execution_allowed": False,
        "required_future_gate_for_execution": D5_REQUIRED_FUTURE_EXECUTION_GATE,
        "learning_recommendation_mode": "report_only",
        "blockers": blockers,
        "warnings": warnings,
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "d4_decision": _json_safe(d4),
    }
    return _json_safe(report)


__all__ = [
    "D5_EXECUTION_METRICS_PHASE",
    "D5_REQUIRED_FUTURE_EXECUTION_GATE",
    "build_phase_d5_execution_metrics_report",
]
