from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from bot.order_store import OPEN_ORDER_STATUSES, OrderStore
from bot.phase_d3_open_exit_lifecycle_manager import (
    build_phase_d3_open_exit_lifecycle_report,
    iter_matching_open_d3_orders,
)
from bot.state_store import StateStore


D3_OPEN_EXIT_MONITOR_PHASE = "D3_open_exit_monitor"
ZERO = Decimal("0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


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


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_iso(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _order_age_minutes(order: Dict[str, Any], *, now: Optional[datetime] = None) -> Optional[int]:
    now_dt = now or _now()
    for key in ("submitted_at", "created_at"):
        dt = _parse_iso(order.get(key))
        if dt is None:
            continue
        delta = now_dt - dt
        return max(0, int(delta.total_seconds() // 60))
    return None


def _stale_open_classification(age_minutes: Optional[int]) -> str:
    if age_minutes is None:
        return "stale_age_unknown"
    if age_minutes < 30:
        return "normal_monitoring"
    if age_minutes <= 120:
        return "stale_watch"
    return "stale_open_review_recommended"


def _find_order(
    store: OrderStore,
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
) -> Optional[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    selected_client = str(client_order_id or "").strip()
    selected_exchange = str(exchange_order_id or "").strip()
    if selected_client:
        order = store.get_order(selected_client)
        if isinstance(order, dict):
            return dict(order)
    for order in store.all_orders():
        if selected_ticker and _normalize_ticker(order.get("ticker")) != selected_ticker:
            continue
        if selected_exchange and str(order.get("exchange_order_id") or order.get("order_id") or "").strip() == selected_exchange:
            return dict(order)
    return None


def _position_coherent_with_open_exit(position: Dict[str, Any], order: Dict[str, Any]) -> bool:
    if not position or not order:
        return False
    if str(position.get("status") or "").strip().lower() != "open":
        return False
    if str(order.get("status") or "").strip().lower() not in OPEN_ORDER_STATUSES:
        return False
    position_base = _to_decimal(position.get("position_size_base"), "0")
    reserved_base = _to_decimal(position.get("reserved_base_open_exit_orders"), "0")
    bot_managed_base = _to_decimal(position.get("bot_managed_base"), "0")
    remaining_size = _to_decimal(order.get("remaining_size") or order.get("size_base"), "0")
    if position_base <= ZERO or bot_managed_base <= ZERO:
        return False
    if reserved_base <= ZERO or remaining_size <= ZERO:
        return False
    if abs(reserved_base - remaining_size) > Decimal("0.0000001"):
        return False
    return bot_managed_base >= (position_base + reserved_base - Decimal("0.0000001"))


def _local_position_drift_detected(position: Dict[str, Any], order: Dict[str, Any]) -> bool:
    if not position or not order:
        return False
    order_open = str(order.get("status") or "").strip().lower() in OPEN_ORDER_STATUSES
    if not order_open:
        return False
    if str(position.get("status") or "").strip().lower() != "open":
        return True
    if _to_decimal(position.get("position_size_base"), "0") <= ZERO:
        return True
    if _to_decimal(position.get("bot_managed_base"), "0") <= ZERO:
        return True
    return False


def _decision_from_reports(
    *,
    local_coherent: bool,
    local_drift: bool,
    duplicate_open_d3_exit_detected: bool,
    lifecycle_report: Dict[str, Any],
    allow_coinbase_poll: bool,
    stale_classification: str,
) -> Dict[str, Any]:
    lifecycle_status = str(lifecycle_report.get("status") or "")
    lifecycle_action = str(lifecycle_report.get("proposed_action") or "")
    lifecycle_blockers = list(lifecycle_report.get("blockers") or [])
    lifecycle_warnings = list(lifecycle_report.get("warnings") or [])
    normalized_status = str(lifecycle_report.get("normalized_status") or "").strip().lower()
    coinbase_call_attempted = bool(lifecycle_report.get("coinbase_call_attempted"))
    coinbase_call_succeeded = bool(lifecycle_report.get("coinbase_call_succeeded"))

    if duplicate_open_d3_exit_detected or bool(lifecycle_report.get("oversell_detected")):
        return {
            "status": "open_exit_monitor_blocked_review_required",
            "operator_decision": "blocked_review_required",
            "next_allowed_action": "manual_review_only",
            "next_forbidden_actions": ["submit", "cancel", "replace", "sell", "apply"],
            "requires_human_approval": True,
            "recommended_next_check": "immediate_manual_review",
            "priority_classification": "P0" if bool(lifecycle_report.get("oversell_detected")) else "P1",
            "blockers": lifecycle_blockers or ["duplicate_or_safety_mismatch"],
            "warnings": lifecycle_warnings,
        }

    if allow_coinbase_poll and coinbase_call_attempted and not coinbase_call_succeeded:
        priority = "P1" if local_drift else "P2"
        return {
            "status": "open_exit_monitor_coinbase_poll_failed",
            "operator_decision": "retry_later_or_use_outside_sandbox_read_only_poll",
            "next_allowed_action": "read_only_coinbase_poll_later",
            "next_forbidden_actions": ["submit", "cancel", "replace", "sell", "apply"],
            "requires_human_approval": False,
            "recommended_next_check": "later_read_only_poll_after_runtime_or_network_is_available",
            "priority_classification": priority,
            "blockers": lifecycle_blockers or ["coinbase_snapshot_unavailable"],
            "warnings": lifecycle_warnings,
        }

    if allow_coinbase_poll and normalized_status in {"partially_filled", "filled", "cancelled", "expired", "rejected"}:
        return {
            "status": "open_exit_monitor_lifecycle_evidence_available",
            "operator_decision": "await_explicit_lifecycle_apply_approval",
            "next_allowed_action": "controlled_d3_lifecycle_apply_with_explicit_approval",
            "next_forbidden_actions": ["submit", "cancel", "replace", "sell", "auto_apply"],
            "requires_human_approval": True,
            "recommended_next_check": "prepare_ack_gated_apply_on_real_evidence",
            "priority_classification": "P1",
            "blockers": lifecycle_blockers,
            "warnings": lifecycle_warnings,
        }

    if local_drift:
        return {
            "status": "open_exit_monitor_local_position_drift",
            "operator_decision": "recovery_required_if_coinbase_open",
            "next_allowed_action": "read_only_coinbase_poll_then_recovery_preview_if_open",
            "next_forbidden_actions": ["submit", "cancel", "replace", "sell", "lifecycle_apply"],
            "requires_human_approval": True,
            "recommended_next_check": "coinbase_open_confirmation_then_recovery_tooling",
            "priority_classification": "P1",
            "blockers": lifecycle_blockers,
            "warnings": lifecycle_warnings,
        }

    if allow_coinbase_poll and normalized_status == "open":
        recommendation = "later_read_only_poll"
        if stale_classification == "stale_watch":
            recommendation = "read_only_poll_later_with_stale_watch"
        elif stale_classification == "stale_open_review_recommended":
            recommendation = "stale_open_review_later"
        return {
            "status": "open_exit_monitor_coinbase_open",
            "operator_decision": "keep_open_and_monitor",
            "next_allowed_action": recommendation,
            "next_forbidden_actions": ["apply", "cancel", "replace", "sell", "submit"],
            "requires_human_approval": False,
            "recommended_next_check": stale_classification,
            "priority_classification": "P1",
            "blockers": lifecycle_blockers,
            "warnings": lifecycle_warnings,
        }

    if local_coherent and not allow_coinbase_poll:
        return {
            "status": "open_exit_monitor_local_coherent",
            "operator_decision": "keep_monitoring",
            "next_allowed_action": "read_only_coinbase_poll_later",
            "next_forbidden_actions": ["submit", "cancel", "replace", "sell", "apply"],
            "requires_human_approval": False,
            "recommended_next_check": stale_classification,
            "priority_classification": "P1",
            "blockers": lifecycle_blockers,
            "warnings": lifecycle_warnings,
        }

    return {
        "status": "open_exit_monitor_blocked_review_required",
        "operator_decision": "blocked_review_required",
        "next_allowed_action": "manual_review_only",
        "next_forbidden_actions": ["submit", "cancel", "replace", "sell", "apply"],
        "requires_human_approval": True,
        "recommended_next_check": "manual_review",
        "priority_classification": "P1",
        "blockers": lifecycle_blockers or [lifecycle_status or lifecycle_action or "unknown_monitor_state"],
        "warnings": lifecycle_warnings,
    }


def build_phase_d3_open_exit_monitor_report(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    allow_coinbase_poll: bool = False,
    snapshot: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    store = order_store or OrderStore()
    positions = state_store or StateStore()
    local_order = _find_order(
        store,
        ticker=selected_ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
    ) or {}
    local_position = positions.get_position(selected_ticker) or {}
    matching_open_orders = iter_matching_open_d3_orders(
        store,
        ticker=selected_ticker,
        position=local_position,
        linked_position_id=linked_position_id,
    )
    order_age_minutes = _order_age_minutes(local_order, now=now)
    stale_classification = _stale_open_classification(order_age_minutes)
    local_coherent = _position_coherent_with_open_exit(local_position, local_order)
    local_drift = _local_position_drift_detected(local_position, local_order)

    lifecycle_report = build_phase_d3_open_exit_lifecycle_report(
        ticker=selected_ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        linked_position_id=linked_position_id,
        order_store=store,
        state_store=positions,
        coinbase_client=coinbase_client,
        snapshot=snapshot,
        allow_coinbase_poll=allow_coinbase_poll,
        apply_local=False,
    )

    decision = _decision_from_reports(
        local_coherent=local_coherent,
        local_drift=local_drift,
        duplicate_open_d3_exit_detected=len(matching_open_orders) > 1,
        lifecycle_report=lifecycle_report,
        allow_coinbase_poll=allow_coinbase_poll,
        stale_classification=stale_classification,
    )

    report: Dict[str, Any] = {
        "status": decision["status"],
        "ticker": selected_ticker,
        "phase": D3_OPEN_EXIT_MONITOR_PHASE,
        "client_order_id": str(client_order_id or "").strip(),
        "exchange_order_id": str(exchange_order_id or "").strip(),
        "linked_position_id": str(linked_position_id or "").strip(),
        "generated_at": _now_iso(),
        "mode": "read_only_coinbase" if allow_coinbase_poll else "local_only",
        "coinbase_call_attempted": bool(lifecycle_report.get("coinbase_call_attempted")),
        "coinbase_call_succeeded": bool(lifecycle_report.get("coinbase_call_succeeded")),
        "state_write_performed": False,
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "live_action_performed": False,
        "local_order_found": bool(local_order),
        "local_order_status": str(local_order.get("status") or ""),
        "local_order_remaining_size": str(local_order.get("remaining_size") or local_order.get("size_base") or "0"),
        "local_order_filled_base": str(local_order.get("filled_base") or local_order.get("filled_size") or "0"),
        "local_order_fill_count": int(local_order.get("fill_count") or 0),
        "local_order_limit_price": str(local_order.get("limit_price") or "0"),
        "local_order_age_minutes": order_age_minutes,
        "duplicate_open_d3_exit_detected": len(matching_open_orders) > 1,
        "oversell_detected": bool(lifecycle_report.get("oversell_detected")),
        "local_position_found": bool(local_position),
        "local_position_status": str(local_position.get("status") or ""),
        "position_size_base": str(local_position.get("position_size_base") or "0"),
        "reserved_base_open_exit_orders": str(local_position.get("reserved_base_open_exit_orders") or "0"),
        "bot_managed_base": str(local_position.get("bot_managed_base") or "0"),
        "position_coherent_with_open_exit": local_coherent,
        "local_position_drift_detected": local_drift,
        "lifecycle_status": str(lifecycle_report.get("status") or ""),
        "lifecycle_proposed_action": str(lifecycle_report.get("proposed_action") or ""),
        "lifecycle_blockers": list(lifecycle_report.get("blockers") or []),
        "lifecycle_warnings": list(lifecycle_report.get("warnings") or []),
        "coinbase_normalized_status": str(lifecycle_report.get("normalized_status") or ""),
        "coinbase_proposed_action": str(lifecycle_report.get("proposed_action") or ""),
        "coinbase_filled_base": str(lifecycle_report.get("filled_base") or "0"),
        "coinbase_filled_quote": str(lifecycle_report.get("filled_quote") or "0"),
        "coinbase_avg_fill_price": str(lifecycle_report.get("avg_fill_price") or "0"),
        "coinbase_fill_count": int(lifecycle_report.get("fill_count") or 0),
        "coinbase_remaining_size": str(lifecycle_report.get("remaining_size") or "0"),
        "coinbase_evidence_hash": str(lifecycle_report.get("evidence_hash") or ""),
        "coinbase_lookup_methods": list(lifecycle_report.get("coinbase_order_lookup_method_attempted") or []),
        "coinbase_lookup_failed_methods": list(lifecycle_report.get("coinbase_order_lookup_failed_methods") or []),
        "coinbase_lookup_succeeded_method": str(lifecycle_report.get("coinbase_order_lookup_succeeded_method") or ""),
        "coinbase_errors": {
            "type": str(lifecycle_report.get("coinbase_error_type") or ""),
            "message": str(lifecycle_report.get("coinbase_error_message") or ""),
            "stage": str(lifecycle_report.get("coinbase_error_stage") or ""),
        },
        "order_id_used": str(lifecycle_report.get("order_id_used") or ""),
        "client_order_id_used": str(lifecycle_report.get("client_order_id_used") or ""),
        "product_id_used": str(lifecycle_report.get("product_id_used") or ""),
        "include_fills": bool(lifecycle_report.get("include_fills", False)),
        "raw_response_shape": _as_dict(lifecycle_report.get("raw_response_shape")),
        "coinbase_warnings": list(lifecycle_report.get("warnings") or []),
        "operator_decision": decision["operator_decision"],
        "next_allowed_action": decision["next_allowed_action"],
        "next_forbidden_actions": decision["next_forbidden_actions"],
        "requires_human_approval": bool(decision["requires_human_approval"]),
        "recommended_next_check": decision["recommended_next_check"],
        "priority_classification": decision["priority_classification"],
        "blockers": decision["blockers"],
        "warnings": decision["warnings"],
        "stale_open_classification": stale_classification,
        "possible_future_branch": (
            "Controlled D.3 Cancel/Replace Review v1"
            if stale_classification == "stale_open_review_recommended"
            else ""
        ),
    }
    return _json_safe(report)


__all__ = [
    "D3_OPEN_EXIT_MONITOR_PHASE",
    "build_phase_d3_open_exit_monitor_report",
]
