from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from bot.order_store import OrderStore
from bot.phase_d3_stale_open_review import build_phase_d3_stale_open_review_report
from bot.state_store import StateStore


D3_CANCEL_REPLACE_REVIEW_PHASE = "D3_cancel_replace_review"
D3_CANCEL_REPLACE_PILOT_ACK = "I_UNDERSTAND_AND_APPROVE_D3_CANCEL_REPLACE_PILOT"


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


def _decision_from_stale_review(report: Dict[str, Any], *, allow_coinbase_poll: bool) -> Dict[str, Any]:
    stale_status = str(report.get("status") or "")
    stale_decision = str(report.get("stale_review_decision") or "")
    coinbase_status = str(report.get("coinbase_normalized_status") or "").strip().lower()
    local_order_status = str(report.get("local_order_status") or "").strip().lower()
    local_position_status = str(report.get("local_position_status") or "").strip().lower()
    position_coherent = bool(report.get("position_coherent_with_open_exit"))
    local_drift = bool(report.get("local_position_drift_detected"))
    duplicate_detected = bool(report.get("duplicate_open_d3_exit_detected"))
    oversell_detected = bool(report.get("oversell_detected"))
    blockers = list(report.get("blockers") or [])
    warnings = list(report.get("warnings") or [])
    remaining_size = str(report.get("coinbase_remaining_size") or report.get("local_order_remaining_size") or "0")
    limit_price = str(report.get("limit_price") or report.get("local_order_limit_price") or "")

    candidate_base = remaining_size
    candidate_side = "SELL"
    candidate_post_only = True
    candidate_reduce_only_semantic = True

    if duplicate_detected or oversell_detected:
        priority = "P0" if oversell_detected or duplicate_detected else "P1"
        return {
            "status": "cancel_replace_review_blocked_safety",
            "cancel_replace_review_status": "blocked_safety",
            "cancel_replace_decision": "blocked_review_required",
            "cancel_replace_reason": "duplicate_or_oversell_safety_mismatch",
            "candidate_cancel_allowed_in_future": False,
            "candidate_replace_allowed_in_future": False,
            "candidate_replace_side": candidate_side,
            "candidate_replace_size_base": candidate_base,
            "candidate_replace_limit_price": "",
            "candidate_replace_post_only": candidate_post_only,
            "candidate_replace_reduce_only_semantic": candidate_reduce_only_semantic,
            "required_future_ack": D3_CANCEL_REPLACE_PILOT_ACK,
            "next_allowed_action": "manual_review_only",
            "next_forbidden_actions": ["direct_cancel", "direct_replace", "new_sell", "lifecycle_apply", "submit"],
            "requires_human_approval": True,
            "priority_classification": priority,
            "blockers": blockers or ["duplicate_or_oversell_safety_mismatch"],
            "warnings": warnings,
        }

    if local_drift or local_position_status != "open":
        return {
            "status": "cancel_replace_review_blocked_local_position_drift",
            "cancel_replace_review_status": "blocked_local_position_drift",
            "cancel_replace_decision": "recovery_required_if_coinbase_open",
            "cancel_replace_reason": "local_position_not_open_or_drift_detected",
            "candidate_cancel_allowed_in_future": False,
            "candidate_replace_allowed_in_future": False,
            "candidate_replace_side": candidate_side,
            "candidate_replace_size_base": candidate_base,
            "candidate_replace_limit_price": "",
            "candidate_replace_post_only": candidate_post_only,
            "candidate_replace_reduce_only_semantic": candidate_reduce_only_semantic,
            "required_future_ack": D3_CANCEL_REPLACE_PILOT_ACK,
            "next_allowed_action": "recovery_preview_after_open_confirmation",
            "next_forbidden_actions": ["cancel", "replace", "sell", "apply"],
            "requires_human_approval": True,
            "priority_classification": "P1",
            "blockers": blockers,
            "warnings": warnings,
        }

    if coinbase_status in {"partially_filled", "filled", "cancelled", "expired", "rejected"}:
        return {
            "status": "cancel_replace_review_not_applicable_lifecycle_evidence_available",
            "cancel_replace_review_status": "lifecycle_evidence_available",
            "cancel_replace_decision": "route_to_controlled_lifecycle_apply",
            "cancel_replace_reason": f"coinbase_status_{coinbase_status}",
            "candidate_cancel_allowed_in_future": False,
            "candidate_replace_allowed_in_future": False,
            "candidate_replace_side": candidate_side,
            "candidate_replace_size_base": candidate_base,
            "candidate_replace_limit_price": "",
            "candidate_replace_post_only": candidate_post_only,
            "candidate_replace_reduce_only_semantic": candidate_reduce_only_semantic,
            "required_future_ack": D3_CANCEL_REPLACE_PILOT_ACK,
            "next_allowed_action": "request_explicit_lifecycle_apply_approval",
            "next_forbidden_actions": ["cancel", "replace", "new_sell", "auto_apply"],
            "requires_human_approval": True,
            "priority_classification": "P1",
            "blockers": blockers,
            "warnings": warnings,
        }

    if allow_coinbase_poll and stale_status == "stale_open_review_coinbase_poll_failed":
        priority = "P2" if position_coherent else "P1"
        return {
            "status": "cancel_replace_review_coinbase_poll_failed",
            "cancel_replace_review_status": "coinbase_poll_failed",
            "cancel_replace_decision": "read_only_coinbase_poll_later_or_outside_sandbox",
            "cancel_replace_reason": "coinbase_evidence_unavailable",
            "candidate_cancel_allowed_in_future": False,
            "candidate_replace_allowed_in_future": False,
            "candidate_replace_side": candidate_side,
            "candidate_replace_size_base": candidate_base,
            "candidate_replace_limit_price": "",
            "candidate_replace_post_only": candidate_post_only,
            "candidate_replace_reduce_only_semantic": candidate_reduce_only_semantic,
            "required_future_ack": D3_CANCEL_REPLACE_PILOT_ACK,
            "next_allowed_action": "read_only_coinbase_poll_later_or_outside_sandbox",
            "next_forbidden_actions": ["cancel", "replace", "sell", "apply"],
            "requires_human_approval": False,
            "priority_classification": priority,
            "blockers": blockers or ["coinbase_snapshot_unavailable"],
            "warnings": warnings,
        }

    if allow_coinbase_poll and coinbase_status == "open" and local_order_status in {"submitted", "open"} and position_coherent:
        decision = "prepare_cancel_replace_pilot"
        reason = "coherent_open_evidence_supports_future_cancel_replace_review"
        next_action = "request_explicit_cancel_replace_pilot_approval"
        if not limit_price:
            decision = "prepare_cancel_replace_pilot_requires_fresh_price_context"
            reason = "fresh_price_context_missing_for_replace_pricing"
            next_action = "read_only_price_context_then_cancel_replace_pilot_review"
        return {
            "status": "cancel_replace_review_ready",
            "cancel_replace_review_status": "ready",
            "cancel_replace_decision": decision,
            "cancel_replace_reason": reason,
            "candidate_cancel_allowed_in_future": True,
            "candidate_replace_allowed_in_future": True,
            "candidate_replace_side": candidate_side,
            "candidate_replace_size_base": candidate_base,
            "candidate_replace_limit_price": limit_price,
            "candidate_replace_post_only": candidate_post_only,
            "candidate_replace_reduce_only_semantic": candidate_reduce_only_semantic,
            "required_future_ack": D3_CANCEL_REPLACE_PILOT_ACK,
            "next_allowed_action": next_action,
            "next_forbidden_actions": ["direct_cancel", "direct_replace", "new_sell", "lifecycle_apply", "submit"],
            "requires_human_approval": True,
            "priority_classification": "P1",
            "blockers": blockers,
            "warnings": warnings,
        }

    if not allow_coinbase_poll and stale_decision in {
        "read_only_coinbase_poll_recommended_before_any_action",
        "prepare_cancel_replace_review_later",
    }:
        return {
            "status": "cancel_replace_review_needs_fresh_open_evidence",
            "cancel_replace_review_status": "needs_fresh_open_evidence",
            "cancel_replace_decision": "run_one_read_only_coinbase_poll_before_pilot",
            "cancel_replace_reason": "fresh_coinbase_open_evidence_required_before_cancel_replace_pilot",
            "candidate_cancel_allowed_in_future": False,
            "candidate_replace_allowed_in_future": False,
            "candidate_replace_side": candidate_side,
            "candidate_replace_size_base": candidate_base,
            "candidate_replace_limit_price": "",
            "candidate_replace_post_only": candidate_post_only,
            "candidate_replace_reduce_only_semantic": candidate_reduce_only_semantic,
            "required_future_ack": D3_CANCEL_REPLACE_PILOT_ACK,
            "next_allowed_action": "read_only_coinbase_poll",
            "next_forbidden_actions": ["direct_cancel", "direct_replace", "new_sell", "lifecycle_apply", "submit"],
            "requires_human_approval": False,
            "priority_classification": "P1",
            "blockers": blockers,
            "warnings": warnings,
        }

    return {
        "status": "cancel_replace_review_blocked_safety",
        "cancel_replace_review_status": "blocked_review_required",
        "cancel_replace_decision": "blocked_review_required",
        "cancel_replace_reason": "cancel_replace_review_state_not_actionable",
        "candidate_cancel_allowed_in_future": False,
        "candidate_replace_allowed_in_future": False,
        "candidate_replace_side": candidate_side,
        "candidate_replace_size_base": candidate_base,
        "candidate_replace_limit_price": "",
        "candidate_replace_post_only": candidate_post_only,
        "candidate_replace_reduce_only_semantic": candidate_reduce_only_semantic,
        "required_future_ack": D3_CANCEL_REPLACE_PILOT_ACK,
        "next_allowed_action": "manual_review_only",
        "next_forbidden_actions": ["direct_cancel", "direct_replace", "new_sell", "lifecycle_apply", "submit"],
        "requires_human_approval": True,
        "priority_classification": "P1",
        "blockers": blockers or ["cancel_replace_review_state_not_actionable"],
        "warnings": warnings,
    }


def build_phase_d3_cancel_replace_review_report(
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
    stale_report = build_phase_d3_stale_open_review_report(
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
    decision = _decision_from_stale_review(stale_report, allow_coinbase_poll=allow_coinbase_poll)
    report = {
        "status": decision["status"],
        "phase": D3_CANCEL_REPLACE_REVIEW_PHASE,
        "ticker": str(ticker or "").strip().upper().replace("/", "-"),
        "client_order_id": str(client_order_id or "").strip(),
        "exchange_order_id": str(exchange_order_id or "").strip(),
        "linked_position_id": str(linked_position_id or "").strip(),
        "generated_at": _now_iso(),
        "mode": "read_only_coinbase" if allow_coinbase_poll else "local_only",
        "state_write_performed": False,
        "coinbase_call_attempted": bool(stale_report.get("coinbase_call_attempted")),
        "coinbase_call_succeeded": bool(stale_report.get("coinbase_call_succeeded")),
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "live_action_performed": False,
        "stale_review_status": str(stale_report.get("stale_review_status") or ""),
        "stale_review_decision": str(stale_report.get("stale_review_decision") or ""),
        "recommended_operator_branch": str(stale_report.get("recommended_operator_branch") or ""),
        "stale_open_classification": str(stale_report.get("stale_open_classification") or ""),
        "local_order_age_minutes": stale_report.get("local_order_age_minutes"),
        "local_order_status": str(stale_report.get("local_order_status") or ""),
        "local_order_remaining_size": str(stale_report.get("coinbase_remaining_size") or stale_report.get("local_order_remaining_size") or "0"),
        "local_order_limit_price": str(stale_report.get("limit_price") or ""),
        "local_order_filled_base": str(stale_report.get("coinbase_filled_base") or "0"),
        "local_order_fill_count": int(stale_report.get("coinbase_fill_count") or 0),
        "local_position_status": str(stale_report.get("local_position_status") or ""),
        "position_size_base": str(stale_report.get("position_size_base") or "0"),
        "reserved_base_open_exit_orders": str(stale_report.get("reserved_base_open_exit_orders") or "0"),
        "bot_managed_base": str(stale_report.get("bot_managed_base") or "0"),
        "position_coherent_with_open_exit": bool(stale_report.get("position_coherent_with_open_exit")),
        "duplicate_open_d3_exit_detected": bool(stale_report.get("duplicate_open_d3_exit_detected")),
        "oversell_detected": bool(stale_report.get("oversell_detected")),
        "coinbase_normalized_status": str(stale_report.get("coinbase_normalized_status") or ""),
        "coinbase_filled_base": str(stale_report.get("coinbase_filled_base") or "0"),
        "coinbase_filled_quote": str(stale_report.get("coinbase_filled_quote") or "0"),
        "coinbase_avg_fill_price": str(stale_report.get("coinbase_avg_fill_price") or "0"),
        "coinbase_fill_count": int(stale_report.get("coinbase_fill_count") or 0),
        "coinbase_remaining_size": str(stale_report.get("coinbase_remaining_size") or "0"),
        "coinbase_evidence_hash": str(stale_report.get("coinbase_evidence_hash") or ""),
        "coinbase_lookup_methods_attempted": list(stale_report.get("coinbase_lookup_methods_attempted") or []),
        "coinbase_lookup_failed_methods": list(stale_report.get("coinbase_lookup_failed_methods") or []),
        "coinbase_lookup_succeeded_method": str(stale_report.get("coinbase_lookup_succeeded_method") or ""),
        "coinbase_errors": dict(stale_report.get("coinbase_errors") or {}),
        "order_id_used": str(stale_report.get("order_id_used") or ""),
        "client_order_id_used": str(stale_report.get("client_order_id_used") or ""),
        "product_id_used": str(stale_report.get("product_id_used") or ""),
        "include_fills": bool(stale_report.get("include_fills", False)),
        "raw_response_shape": dict(stale_report.get("raw_response_shape") or {}),
        "coinbase_warnings": list(stale_report.get("coinbase_warnings") or []),
        "cancel_replace_review_status": decision["cancel_replace_review_status"],
        "cancel_replace_decision": decision["cancel_replace_decision"],
        "cancel_replace_reason": decision["cancel_replace_reason"],
        "candidate_cancel_allowed_in_future": bool(decision["candidate_cancel_allowed_in_future"]),
        "candidate_replace_allowed_in_future": bool(decision["candidate_replace_allowed_in_future"]),
        "candidate_replace_side": str(decision["candidate_replace_side"]),
        "candidate_replace_size_base": str(decision["candidate_replace_size_base"]),
        "candidate_replace_limit_price": str(decision["candidate_replace_limit_price"]),
        "candidate_replace_post_only": bool(decision["candidate_replace_post_only"]),
        "candidate_replace_reduce_only_semantic": bool(decision["candidate_replace_reduce_only_semantic"]),
        "required_future_ack": str(decision["required_future_ack"]),
        "next_allowed_action": str(decision["next_allowed_action"]),
        "next_forbidden_actions": list(decision["next_forbidden_actions"]),
        "requires_human_approval": bool(decision["requires_human_approval"]),
        "priority_classification": str(decision["priority_classification"]),
        "blockers": list(decision["blockers"]),
        "warnings": list(decision["warnings"]),
    }
    return _json_safe(report)


__all__ = [
    "D3_CANCEL_REPLACE_PILOT_ACK",
    "D3_CANCEL_REPLACE_REVIEW_PHASE",
    "build_phase_d3_cancel_replace_review_report",
]
