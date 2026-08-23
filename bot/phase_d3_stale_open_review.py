from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from bot.phase_d3_open_exit_monitor import build_phase_d3_open_exit_monitor_report
from bot.order_store import OrderStore
from bot.state_store import StateStore


D3_STALE_OPEN_REVIEW_PHASE = "D3_stale_open_review"


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


def _market_context(report: Dict[str, Any]) -> Dict[str, Any]:
    limit_price = str(report.get("local_order_limit_price") or "0")
    has_context = limit_price not in {"", "0", "0.0"}
    return {
        "limit_price": limit_price,
        "current_bid": "",
        "current_ask": "",
        "distance_to_limit_pct": "",
        "stale_review_market_context_available": has_context,
    }


def _decision_from_monitor(report: Dict[str, Any], *, allow_coinbase_poll: bool) -> Dict[str, Any]:
    monitor_status = str(report.get("status") or "")
    monitor_operator_decision = str(report.get("operator_decision") or "")
    stale_classification = str(report.get("stale_open_classification") or "")
    coinbase_status = str(report.get("coinbase_normalized_status") or "").strip().lower()
    local_coherent = bool(report.get("position_coherent_with_open_exit"))
    local_drift = bool(report.get("local_position_drift_detected"))
    duplicate_detected = bool(report.get("duplicate_open_d3_exit_detected"))
    lifecycle_blockers = list(report.get("lifecycle_blockers") or [])
    lifecycle_warnings = list(report.get("lifecycle_warnings") or [])
    blockers = list(report.get("blockers") or [])
    warnings = list(report.get("warnings") or [])
    coinbase_succeeded = bool(report.get("coinbase_call_succeeded"))

    if duplicate_detected or monitor_status == "open_exit_monitor_blocked_review_required":
        priority = "P0" if "open_d3_exit_reservation_exceeds_manageable_base" in lifecycle_blockers else "P1"
        return {
            "status": "stale_open_review_blocked_review_required",
            "stale_review_status": "blocked_review_required",
            "stale_review_decision": "blocked_review_required",
            "stale_review_reason": "duplicate_or_safety_mismatch",
            "recommended_operator_branch": "manual_review_only",
            "next_allowed_action": "manual_review_only",
            "next_forbidden_actions": ["submit", "cancel", "replace", "sell", "apply"],
            "requires_human_approval": True,
            "priority_classification": priority,
            "blockers": blockers or lifecycle_blockers or ["duplicate_or_safety_mismatch"],
            "warnings": warnings or lifecycle_warnings,
        }

    if local_drift:
        return {
            "status": "stale_open_review_local_position_drift",
            "stale_review_status": "local_position_drift",
            "stale_review_decision": "recovery_required_if_coinbase_open",
            "stale_review_reason": "open_order_with_local_position_drift",
            "recommended_operator_branch": "read_only_coinbase_poll_then_recovery_preview_if_open",
            "next_allowed_action": "read_only_coinbase_poll",
            "next_forbidden_actions": ["cancel", "replace", "sell", "apply"],
            "requires_human_approval": True,
            "priority_classification": "P1",
            "blockers": blockers or lifecycle_blockers,
            "warnings": warnings or lifecycle_warnings,
        }

    if allow_coinbase_poll and not coinbase_succeeded:
        priority = "P2" if local_coherent else "P1"
        return {
            "status": "stale_open_review_coinbase_poll_failed",
            "stale_review_status": "coinbase_poll_failed",
            "stale_review_decision": "retry_later_or_use_outside_sandbox_read_only_poll",
            "stale_review_reason": "coinbase_evidence_unavailable",
            "recommended_operator_branch": "read_only_coinbase_poll_later",
            "next_allowed_action": "read_only_coinbase_poll_later",
            "next_forbidden_actions": ["cancel", "replace", "sell", "apply"],
            "requires_human_approval": False,
            "priority_classification": priority,
            "blockers": blockers or lifecycle_blockers or ["coinbase_snapshot_unavailable"],
            "warnings": warnings or lifecycle_warnings,
        }

    if allow_coinbase_poll and coinbase_status in {"partially_filled", "filled", "cancelled", "expired", "rejected"}:
        return {
            "status": "stale_open_review_lifecycle_evidence_available",
            "stale_review_status": "lifecycle_evidence_available",
            "stale_review_decision": "await_explicit_d3_lifecycle_apply_approval",
            "stale_review_reason": f"coinbase_status_{coinbase_status}",
            "recommended_operator_branch": "Controlled D.3 lifecycle apply on real evidence",
            "next_allowed_action": "request_explicit_lifecycle_apply_approval",
            "next_forbidden_actions": ["auto_apply", "cancel", "replace", "new_sell"],
            "requires_human_approval": True,
            "priority_classification": "P1",
            "blockers": blockers or lifecycle_blockers,
            "warnings": warnings or lifecycle_warnings,
        }

    if allow_coinbase_poll and coinbase_status == "open":
        return {
            "status": "stale_open_review_coinbase_open",
            "stale_review_status": "coinbase_open_confirmed",
            "stale_review_decision": "prepare_cancel_replace_review_later",
            "stale_review_reason": "stale_open_confirmed_by_coinbase_open_evidence",
            "recommended_operator_branch": "Controlled D.3 Cancel/Replace Review v1",
            "next_allowed_action": "prepare_cancel_replace_review_only",
            "next_forbidden_actions": ["direct_cancel", "direct_replace", "new_sell", "lifecycle_apply", "submit"],
            "requires_human_approval": True,
            "priority_classification": "P1",
            "blockers": blockers or lifecycle_blockers,
            "warnings": warnings or lifecycle_warnings,
        }

    if stale_classification == "stale_open_review_recommended":
        return {
            "status": "stale_open_review_local_only_ready",
            "stale_review_status": "local_only_ready",
            "stale_review_decision": "read_only_coinbase_poll_recommended_before_any_action",
            "stale_review_reason": "stale_open_review_recommended_without_live_evidence",
            "recommended_operator_branch": "run_one_read_only_coinbase_poll",
            "next_allowed_action": "read_only_coinbase_poll",
            "next_forbidden_actions": ["submit", "cancel", "replace", "sell", "apply"],
            "requires_human_approval": False,
            "priority_classification": "P1",
            "blockers": blockers or lifecycle_blockers,
            "warnings": warnings or lifecycle_warnings,
        }

    return {
        "status": "stale_open_review_not_needed_yet",
        "stale_review_status": "not_needed_yet",
        "stale_review_decision": "keep_monitoring",
        "stale_review_reason": monitor_operator_decision or "monitoring_continues",
        "recommended_operator_branch": "keep_open_and_monitor",
        "next_allowed_action": "read_only_coinbase_poll_later",
        "next_forbidden_actions": ["submit", "cancel", "replace", "sell", "apply"],
        "requires_human_approval": False,
        "priority_classification": "P1",
        "blockers": blockers or lifecycle_blockers,
        "warnings": warnings or lifecycle_warnings,
    }


def build_phase_d3_stale_open_review_report(
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
    monitor_report = build_phase_d3_open_exit_monitor_report(
        ticker=ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        linked_position_id=linked_position_id,
        order_store=order_store,
        state_store=state_store,
        coinbase_client=coinbase_client,
        allow_coinbase_poll=allow_coinbase_poll,
        snapshot=snapshot,
        now=now,
    )
    decision = _decision_from_monitor(monitor_report, allow_coinbase_poll=allow_coinbase_poll)
    market = _market_context(monitor_report)
    report = {
        "status": decision["status"],
        "phase": D3_STALE_OPEN_REVIEW_PHASE,
        "ticker": str(ticker or "").strip().upper().replace("/", "-"),
        "client_order_id": str(client_order_id or "").strip(),
        "exchange_order_id": str(exchange_order_id or "").strip(),
        "linked_position_id": str(linked_position_id or "").strip(),
        "generated_at": _now_iso(),
        "mode": "read_only_coinbase" if allow_coinbase_poll else "local_only",
        "state_write_performed": False,
        "coinbase_call_attempted": bool(monitor_report.get("coinbase_call_attempted")),
        "coinbase_call_succeeded": bool(monitor_report.get("coinbase_call_succeeded")),
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "live_action_performed": False,
        "monitor_status": str(monitor_report.get("status") or ""),
        "monitor_operator_decision": str(monitor_report.get("operator_decision") or ""),
        "monitor_next_allowed_action": str(monitor_report.get("next_allowed_action") or ""),
        "monitor_forbidden_actions": list(monitor_report.get("next_forbidden_actions") or []),
        "stale_open_classification": str(monitor_report.get("stale_open_classification") or ""),
        "local_order_age_minutes": monitor_report.get("local_order_age_minutes"),
        "local_order_status": str(monitor_report.get("local_order_status") or ""),
        "local_order_remaining_size": str(monitor_report.get("local_order_remaining_size") or "0"),
        "local_order_limit_price": str(monitor_report.get("local_order_limit_price") or "0"),
        "local_order_filled_base": str(monitor_report.get("local_order_filled_base") or "0"),
        "local_order_fill_count": int(monitor_report.get("local_order_fill_count") or 0),
        "local_position_status": str(monitor_report.get("local_position_status") or ""),
        "position_size_base": str(monitor_report.get("position_size_base") or "0"),
        "reserved_base_open_exit_orders": str(monitor_report.get("reserved_base_open_exit_orders") or "0"),
        "bot_managed_base": str(monitor_report.get("bot_managed_base") or "0"),
        "position_coherent_with_open_exit": bool(monitor_report.get("position_coherent_with_open_exit")),
        "local_position_drift_detected": bool(monitor_report.get("local_position_drift_detected")),
        "duplicate_open_d3_exit_detected": bool(monitor_report.get("duplicate_open_d3_exit_detected")),
        "oversell_detected": bool(monitor_report.get("oversell_detected")),
        "coinbase_normalized_status": str(monitor_report.get("coinbase_normalized_status") or ""),
        "coinbase_proposed_action": str(monitor_report.get("coinbase_proposed_action") or ""),
        "coinbase_filled_base": str(monitor_report.get("coinbase_filled_base") or "0"),
        "coinbase_filled_quote": str(monitor_report.get("coinbase_filled_quote") or "0"),
        "coinbase_avg_fill_price": str(monitor_report.get("coinbase_avg_fill_price") or "0"),
        "coinbase_fill_count": int(monitor_report.get("coinbase_fill_count") or 0),
        "coinbase_remaining_size": str(monitor_report.get("coinbase_remaining_size") or "0"),
        "coinbase_evidence_hash": str(monitor_report.get("coinbase_evidence_hash") or ""),
        "coinbase_lookup_methods_attempted": list(monitor_report.get("coinbase_lookup_methods") or []),
        "coinbase_lookup_failed_methods": list(monitor_report.get("coinbase_lookup_failed_methods") or []),
        "coinbase_lookup_succeeded_method": str(monitor_report.get("coinbase_lookup_succeeded_method") or ""),
        "coinbase_errors": dict(monitor_report.get("coinbase_errors") or {}),
        "order_id_used": str(monitor_report.get("order_id_used") or ""),
        "client_order_id_used": str(monitor_report.get("client_order_id_used") or ""),
        "product_id_used": str(monitor_report.get("product_id_used") or ""),
        "include_fills": bool(monitor_report.get("include_fills", False)),
        "raw_response_shape": dict(monitor_report.get("raw_response_shape") or {}),
        "coinbase_warnings": list(monitor_report.get("coinbase_warnings") or []),
        "stale_review_status": decision["stale_review_status"],
        "stale_review_decision": decision["stale_review_decision"],
        "stale_review_reason": decision["stale_review_reason"],
        "recommended_operator_branch": decision["recommended_operator_branch"],
        "next_allowed_action": decision["next_allowed_action"],
        "next_forbidden_actions": decision["next_forbidden_actions"],
        "requires_human_approval": bool(decision["requires_human_approval"]),
        "priority_classification": decision["priority_classification"],
        "blockers": decision["blockers"],
        "warnings": decision["warnings"],
        **market,
    }
    return _json_safe(report)


__all__ = [
    "D3_STALE_OPEN_REVIEW_PHASE",
    "build_phase_d3_stale_open_review_report",
]
