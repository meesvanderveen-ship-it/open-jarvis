from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from bot.phase_d3_live_exit_reconciliation import D3_LIVE_EXIT_RECONCILE_ACK
from bot.phase_d3_open_exit_lifecycle_manager import D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK


D45_EXIT_OPERATIONS_PHASE = "D45_exit_operations_hardening_v1"
FILL_APPLY_ROUTE = "Controlled D.3 Lifecycle Apply on Fill Evidence v1"
TERMINAL_CLOSEOUT_ROUTE = "Controlled D.3 Terminal Closeout Reconcile v1"
ZERO = Decimal("0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or str(value).strip() == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    aliases = {
        "open": "open",
        "open/open": "open",
        "submitted": "open",
        "partial": "partial",
        "partially_filled": "partial",
        "filled": "filled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
    }
    return aliases.get(status, status or "unknown")


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


def target_distance_band(*, limit_price: Any, market_mid: Any) -> Dict[str, Any]:
    limit = _to_decimal(limit_price, "0")
    mid = _to_decimal(market_mid, "0")
    if limit <= ZERO or mid <= ZERO:
        return {
            "market_mid": str(market_mid or ""),
            "limit_price": str(limit_price or ""),
            "distance_abs": "",
            "distance_pct_of_limit": "",
            "band": "unknown",
            "market_trigger": False,
        }
    distance = limit - mid
    distance_abs = abs(distance)
    pct = distance_abs / limit
    if pct <= Decimal("0.01"):
        band = "near_target"
        trigger = True
    elif pct <= Decimal("0.03"):
        band = "approaching_target"
        trigger = True
    else:
        band = "far_from_target"
        trigger = False
    return {
        "market_mid": str(mid),
        "limit_price": str(limit),
        "distance_abs": str(distance_abs),
        "distance_pct_of_limit": str(pct),
        "band": band,
        "market_trigger": trigger,
    }


def _local_safety_blockers(local_report: Dict[str, Any]) -> list[str]:
    blockers = list(local_report.get("blockers") or [])
    if str(local_report.get("recommended_operator_action") or "") == "blocked_p0_review_required":
        blockers.append("local_d45_blocked_p0_review_required")
    if int(_to_decimal(local_report.get("open_d3_exit_count_for_position"), "0")) != 1:
        blockers.append("open_exit_count_not_exactly_one")
    reserved = _to_decimal(local_report.get("reserved_base_open_exit_orders"), "0")
    remaining = _to_decimal(local_report.get("remaining_size"), "0")
    if remaining > ZERO and reserved != remaining:
        blockers.append("reservation_not_equal_remaining_size")
    return list(dict.fromkeys(blockers))


def evaluate_trigger_policy(
    *,
    local_report: Dict[str, Any],
    limit_price: Any,
    market_mid: Any = "",
    explicit_operator_request: bool = False,
    lifecycle_evidence_hint: bool = False,
    enough_time_elapsed: bool = False,
    updated_lifecycle_check_useful: bool = False,
) -> Dict[str, Any]:
    safety_blockers = _local_safety_blockers(local_report)
    market = target_distance_band(limit_price=limit_price, market_mid=market_mid)
    reasons: list[str] = []
    if explicit_operator_request:
        reasons.append("explicit_operator_request")
    if lifecycle_evidence_hint:
        reasons.append("lifecycle_evidence_hint")
    if safety_blockers:
        reasons.append("safety_drift")
    if bool(market.get("market_trigger")):
        reasons.append(f"market_{market.get('band')}")
    if enough_time_elapsed and updated_lifecycle_check_useful:
        reasons.append("time_elapsed_updated_check_useful")

    trigger = bool(reasons)
    return {
        "trigger": trigger,
        "reasons": reasons,
        "market": market,
        "safety_blockers": safety_blockers,
        "poll_allowed": trigger and not safety_blockers,
        "poll_policy": "poll_once_read_only" if trigger and not safety_blockers else "do_not_poll",
    }


def _poll_branch(poll_report: Dict[str, Any]) -> Dict[str, Any]:
    blockers = list(poll_report.get("blockers") or [])
    if blockers or not bool(poll_report.get("coinbase_call_succeeded", True)):
        return {
            "lifecycle_branch": "fail_closed",
            "recommended_operator_action": "blocked_review_required",
            "next_route": "diagnose_poll_or_safety_failure",
            "required_future_ack": "",
        }
    status = _normalize_status(
        poll_report.get("normalized_status")
        or poll_report.get("lifecycle_status")
        or poll_report.get("status")
        or poll_report.get("coinbase_raw_status")
    )
    filled_base = _to_decimal(poll_report.get("filled_base"), "0")
    fill_count = _to_int(poll_report.get("fill_count"), 0)
    if status == "open" and filled_base <= ZERO and fill_count == 0:
        return {
            "lifecycle_branch": "open_keep_open",
            "recommended_operator_action": "wait_for_trigger",
            "next_route": "keep_open",
            "required_future_ack": "",
        }
    if status in {"partial", "filled"} or filled_base > ZERO or fill_count > 0:
        return {
            "lifecycle_branch": "fill_evidence",
            "recommended_operator_action": "prepare_fill_lifecycle_apply",
            "next_route": FILL_APPLY_ROUTE,
            "required_future_ack": D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
        }
    if status in {"cancelled", "expired", "rejected"}:
        return {
            "lifecycle_branch": "terminal_evidence",
            "recommended_operator_action": "prepare_terminal_closeout",
            "next_route": TERMINAL_CLOSEOUT_ROUTE,
            "required_future_ack": D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
            "inner_reconcile_ack": D3_LIVE_EXIT_RECONCILE_ACK,
        }
    return {
        "lifecycle_branch": "fail_closed",
        "recommended_operator_action": "blocked_review_required",
        "next_route": "unknown_lifecycle_status_review",
        "required_future_ack": "",
    }


def build_phase_d45_exit_operations_report(
    *,
    local_report: Dict[str, Any],
    active_order: Optional[Dict[str, Any]] = None,
    lifecycle_poll_report: Optional[Dict[str, Any]] = None,
    d5_metrics_report: Optional[Dict[str, Any]] = None,
    market_mid: Any = "",
    explicit_operator_request: bool = False,
    lifecycle_evidence_hint: bool = False,
    enough_time_elapsed: bool = False,
    updated_lifecycle_check_useful: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now_dt = now or _now()
    order = dict(active_order or local_report.get("active_order_summary") or {})
    limit_price = order.get("limit_price") or local_report.get("active_order_summary", {}).get("limit_price") or ""
    trigger = evaluate_trigger_policy(
        local_report=local_report,
        limit_price=limit_price,
        market_mid=market_mid,
        explicit_operator_request=explicit_operator_request,
        lifecycle_evidence_hint=lifecycle_evidence_hint,
        enough_time_elapsed=enough_time_elapsed,
        updated_lifecycle_check_useful=updated_lifecycle_check_useful,
    )
    safety_blockers = list(trigger.get("safety_blockers") or [])
    poll_executed = lifecycle_poll_report is not None

    if safety_blockers:
        branch = {
            "lifecycle_branch": "blocked_p0_safety_drift",
            "recommended_operator_action": "blocked_p0_review_required",
            "next_route": "p0_safety_review",
            "required_future_ack": "",
        }
    elif not trigger.get("trigger"):
        branch = {
            "lifecycle_branch": "open_keep_open",
            "recommended_operator_action": "wait_for_trigger",
            "next_route": "do_not_poll_wait_for_trigger",
            "required_future_ack": "",
        }
    elif not poll_executed:
        branch = {
            "lifecycle_branch": "poll_required_not_executed",
            "recommended_operator_action": "run_one_read_only_lifecycle_poll",
            "next_route": "one_read_only_lifecycle_poll",
            "required_future_ack": "",
        }
    else:
        branch = _poll_branch(dict(lifecycle_poll_report or {}))

    report = {
        "generated_at": now_dt.isoformat(),
        "phase": D45_EXIT_OPERATIONS_PHASE,
        "status": "d45_exit_operations_report_ready" if not safety_blockers else "d45_exit_operations_blocked_p0",
        "active_order_summary": order,
        "local_d45_summary": {
            "lifecycle_branch": str(local_report.get("lifecycle_branch") or ""),
            "recommended_operator_action": str(local_report.get("recommended_operator_action") or ""),
            "open_d3_exit_count_for_position": local_report.get("open_d3_exit_count_for_position"),
            "reserved_base_open_exit_orders": str(local_report.get("reserved_base_open_exit_orders") or ""),
            "remaining_size": str(local_report.get("remaining_size") or ""),
            "blockers": list(local_report.get("blockers") or []),
        },
        "trigger_evaluation": trigger,
        "poll_executed": poll_executed,
        "poll_report_summary": {
            "coinbase_raw_status": str((lifecycle_poll_report or {}).get("coinbase_raw_status") or ""),
            "normalized_status": str((lifecycle_poll_report or {}).get("normalized_status") or ""),
            "filled_base": str((lifecycle_poll_report or {}).get("filled_base") or "0"),
            "fill_count": _to_int((lifecycle_poll_report or {}).get("fill_count"), 0),
            "remaining_size": str((lifecycle_poll_report or {}).get("remaining_size") or ""),
            "proposed_action": str((lifecycle_poll_report or {}).get("proposed_action") or ""),
            "blockers": list((lifecycle_poll_report or {}).get("blockers") or []),
        },
        "d5_no_fill_stale_summary": {
            "no_fill_duration_seconds": str((d5_metrics_report or {}).get("no_fill_duration_seconds") or ""),
            "stale_order_age_seconds": str((d5_metrics_report or {}).get("stale_order_age_seconds") or ""),
            "target_distance_band": str((d5_metrics_report or {}).get("target_distance_band") or trigger["market"].get("band") or ""),
            "target_distance_pct": str((d5_metrics_report or {}).get("target_distance_pct") or trigger["market"].get("distance_pct_of_limit") or ""),
            "no_fill_recommendation_label": str((d5_metrics_report or {}).get("no_fill_recommendation_label") or ""),
            "learning_to_execution_allowed": bool((d5_metrics_report or {}).get("learning_to_execution_allowed", False)),
        },
        "lifecycle_branch": branch["lifecycle_branch"],
        "recommended_operator_action": branch["recommended_operator_action"],
        "next_route": branch["next_route"],
        "required_future_ack": branch.get("required_future_ack", ""),
        "inner_reconcile_ack": branch.get("inner_reconcile_ack", ""),
        "blockers": safety_blockers if safety_blockers else list((lifecycle_poll_report or {}).get("blockers") or []),
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "no_coinbase_write": True,
        "no_live_action": True,
        "state_write_performed": False,
        "learning_to_execution_allowed": False,
    }
    return _json_safe(report)


__all__ = [
    "D45_EXIT_OPERATIONS_PHASE",
    "FILL_APPLY_ROUTE",
    "TERMINAL_CLOSEOUT_ROUTE",
    "build_phase_d45_exit_operations_report",
    "evaluate_trigger_policy",
    "target_distance_band",
]
