from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from bot.order_store import OrderStore
from bot.phase_d3_cancel_replace_review import (
    D3_CANCEL_REPLACE_PILOT_ACK,
    build_phase_d3_cancel_replace_review_report,
)
from bot.state_store import StateStore


D3_CANCEL_REPLACE_PILOT_PREFLIGHT_PHASE = "D3_cancel_replace_pilot_preflight"


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


def _decision_from_review(report: Dict[str, Any], *, allow_coinbase_poll: bool) -> Dict[str, Any]:
    review_status = str(report.get("status") or "")
    review_decision = str(report.get("cancel_replace_decision") or "")
    coinbase_status = str(report.get("coinbase_normalized_status") or "").strip().lower()
    remaining_size = str(report.get("coinbase_remaining_size") or report.get("local_order_remaining_size") or "0")
    limit_price = str(report.get("local_order_limit_price") or "")
    has_limit_price = limit_price not in {"", "0", "0.0"}
    local_position_status = str(report.get("local_position_status") or "").strip().lower()
    duplicate_detected = bool(report.get("duplicate_open_d3_exit_detected"))
    oversell_detected = bool(report.get("oversell_detected"))
    reservation = Decimal(str(report.get("reserved_base_open_exit_orders") or "0"))
    position_size = Decimal(str(report.get("position_size_base") or "0"))
    remaining = Decimal(str(remaining_size or "0"))
    reservation_covers_remaining_size = reservation >= remaining
    position_open_and_manageable = local_position_status == "open" and position_size > Decimal("0")
    candidate_size_within_position = remaining <= position_size + reservation
    blockers = list(report.get("blockers") or [])
    warnings = list(report.get("warnings") or [])

    common = {
        "candidate_cancel_order_id": str(report.get("exchange_order_id") or ""),
        "candidate_cancel_client_order_id": str(report.get("client_order_id") or ""),
        "candidate_replace_side": "SELL",
        "candidate_replace_size_base": remaining_size,
        "candidate_replace_limit_price": limit_price if has_limit_price else "",
        "candidate_replace_post_only": True,
        "candidate_replace_reduce_only_semantic": True,
        "candidate_replace_requires_fresh_price": False,
        "candidate_replace_price_source": "existing_open_order_limit_price" if has_limit_price else "",
        "required_ack_for_future_pilot": D3_CANCEL_REPLACE_PILOT_ACK,
    }

    if duplicate_detected or oversell_detected or not reservation_covers_remaining_size or not candidate_size_within_position:
        priority = "P0" if duplicate_detected or oversell_detected else "P1"
        return {
            "status": "cancel_replace_pilot_preflight_blocked_safety",
            "preflight_status": "blocked_safety",
            "preflight_decision": "manual_review_only",
            "preflight_reason": "duplicate_oversell_or_reservation_mismatch",
            "pilot_candidate_ready": False,
            "cancel_leg_ready": False,
            "replace_leg_ready": False,
            "next_allowed_action": "manual_review_only",
            "next_forbidden_actions": ["cancel", "replace", "submit", "sell", "lifecycle_apply"],
            "requires_human_approval": True,
            "priority_classification": priority,
            "blockers": blockers or ["duplicate_oversell_or_reservation_mismatch"],
            "warnings": warnings,
            **common,
        }

    if review_status == "cancel_replace_review_blocked_local_position_drift" or not position_open_and_manageable:
        return {
            "status": "cancel_replace_pilot_preflight_blocked_local_position_drift",
            "preflight_status": "blocked_local_position_drift",
            "preflight_decision": "recovery_required_if_coinbase_open",
            "preflight_reason": "local_position_not_open_or_manageable",
            "pilot_candidate_ready": False,
            "cancel_leg_ready": False,
            "replace_leg_ready": False,
            "next_allowed_action": "recovery_preview_after_open_confirmation",
            "next_forbidden_actions": ["cancel", "replace", "submit", "sell", "lifecycle_apply"],
            "requires_human_approval": True,
            "priority_classification": "P1",
            "blockers": blockers,
            "warnings": warnings,
            **common,
        }

    if review_status == "cancel_replace_review_coinbase_poll_failed":
        priority = "P2" if position_open_and_manageable else "P1"
        return {
            "status": "cancel_replace_pilot_preflight_coinbase_poll_failed",
            "preflight_status": "coinbase_poll_failed",
            "preflight_decision": "retry_later_or_use_outside_sandbox_read_only_poll",
            "preflight_reason": "coinbase_evidence_unavailable",
            "pilot_candidate_ready": False,
            "cancel_leg_ready": False,
            "replace_leg_ready": False,
            "next_allowed_action": "read_only_coinbase_poll_later_or_outside_sandbox",
            "next_forbidden_actions": ["cancel", "replace", "submit", "sell", "lifecycle_apply"],
            "requires_human_approval": False,
            "priority_classification": priority,
            "blockers": blockers or ["coinbase_snapshot_unavailable"],
            "warnings": warnings,
            **common,
        }

    if coinbase_status in {"partially_filled", "filled", "cancelled", "expired", "rejected"}:
        return {
            "status": "cancel_replace_pilot_preflight_not_applicable_lifecycle_evidence_available",
            "preflight_status": "lifecycle_evidence_available",
            "preflight_decision": "route_to_controlled_lifecycle_apply",
            "preflight_reason": f"coinbase_status_{coinbase_status}",
            "pilot_candidate_ready": False,
            "cancel_leg_ready": False,
            "replace_leg_ready": False,
            "next_allowed_action": "request_explicit_lifecycle_apply_approval",
            "next_forbidden_actions": ["cancel", "replace", "submit", "sell"],
            "requires_human_approval": True,
            "priority_classification": "P1",
            "blockers": blockers,
            "warnings": warnings,
            **common,
        }

    if not allow_coinbase_poll or review_decision == "run_one_read_only_coinbase_poll_before_pilot":
        return {
            "status": "cancel_replace_pilot_preflight_needs_fresh_open_evidence",
            "preflight_status": "needs_fresh_open_evidence",
            "preflight_decision": "run_one_read_only_coinbase_poll_before_pilot",
            "preflight_reason": "fresh_open_evidence_required_before_cancel_replace_pilot",
            "pilot_candidate_ready": False,
            "cancel_leg_ready": False,
            "replace_leg_ready": False,
            "next_allowed_action": "read_only_coinbase_poll",
            "next_forbidden_actions": ["cancel", "replace", "submit", "sell", "lifecycle_apply"],
            "requires_human_approval": False,
            "priority_classification": "P1",
            "blockers": blockers,
            "warnings": warnings,
            **common,
        }

    if coinbase_status == "open" and not has_limit_price:
        return {
            "status": "cancel_replace_pilot_preflight_needs_price_context",
            "preflight_status": "needs_price_context",
            "preflight_decision": "collect_read_only_price_context_before_pilot",
            "preflight_reason": "candidate_replace_limit_price_missing",
            "pilot_candidate_ready": False,
            "cancel_leg_ready": True,
            "replace_leg_ready": False,
            "next_allowed_action": "read_only_price_context",
            "next_forbidden_actions": ["auto_cancel", "auto_replace", "submit", "sell", "lifecycle_apply"],
            "requires_human_approval": True,
            "priority_classification": "P1",
            "blockers": blockers,
            "warnings": warnings,
            **{
                **common,
                "candidate_replace_requires_fresh_price": True,
                "candidate_replace_price_source": "",
            },
        }

    if coinbase_status == "open":
        return {
            "status": "cancel_replace_pilot_preflight_ready",
            "preflight_status": "ready",
            "preflight_decision": "ready_for_explicit_cancel_replace_pilot_approval",
            "preflight_reason": "fresh_open_evidence_and_local_invariants_green",
            "pilot_candidate_ready": True,
            "cancel_leg_ready": True,
            "replace_leg_ready": True,
            "next_allowed_action": "request_explicit_cancel_replace_pilot_approval",
            "next_forbidden_actions": ["auto_cancel", "auto_replace", "new_sell_without_cancel", "lifecycle_apply"],
            "requires_human_approval": True,
            "priority_classification": "P1",
            "blockers": blockers,
            "warnings": warnings,
            **common,
        }

    return {
        "status": "cancel_replace_pilot_preflight_blocked_safety",
        "preflight_status": "blocked_review_required",
        "preflight_decision": "manual_review_only",
        "preflight_reason": "preflight_state_not_actionable",
        "pilot_candidate_ready": False,
        "cancel_leg_ready": False,
        "replace_leg_ready": False,
        "next_allowed_action": "manual_review_only",
        "next_forbidden_actions": ["cancel", "replace", "submit", "sell", "lifecycle_apply"],
        "requires_human_approval": True,
        "priority_classification": "P1",
        "blockers": blockers or ["preflight_state_not_actionable"],
        "warnings": warnings,
        **common,
    }


def build_phase_d3_cancel_replace_pilot_preflight_report(
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
    review_report = build_phase_d3_cancel_replace_review_report(
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
    decision = _decision_from_review(review_report, allow_coinbase_poll=allow_coinbase_poll)
    report = {
        "status": decision["status"],
        "phase": D3_CANCEL_REPLACE_PILOT_PREFLIGHT_PHASE,
        "ticker": str(ticker or "").strip().upper().replace("/", "-"),
        "client_order_id": str(client_order_id or "").strip(),
        "exchange_order_id": str(exchange_order_id or "").strip(),
        "linked_position_id": str(linked_position_id or "").strip(),
        "generated_at": _now_iso(),
        "mode": "read_only_coinbase" if allow_coinbase_poll else "local_only",
        "state_write_performed": False,
        "coinbase_call_attempted": bool(review_report.get("coinbase_call_attempted")),
        "coinbase_call_succeeded": bool(review_report.get("coinbase_call_succeeded")),
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "live_action_performed": False,
        "cancel_replace_review_status": str(review_report.get("status") or ""),
        "cancel_replace_decision": str(review_report.get("cancel_replace_decision") or ""),
        "required_future_ack": str(review_report.get("required_future_ack") or D3_CANCEL_REPLACE_PILOT_ACK),
        "next_allowed_action_from_review": str(review_report.get("next_allowed_action") or ""),
        "priority_classification_from_review": str(review_report.get("priority_classification") or ""),
        "local_order_status": str(review_report.get("local_order_status") or ""),
        "local_order_remaining_size": str(review_report.get("local_order_remaining_size") or "0"),
        "local_order_limit_price": str(review_report.get("local_order_limit_price") or ""),
        "local_position_status": str(review_report.get("local_position_status") or ""),
        "position_size_base": str(review_report.get("position_size_base") or "0"),
        "reserved_base_open_exit_orders": str(review_report.get("reserved_base_open_exit_orders") or "0"),
        "bot_managed_base": str(review_report.get("bot_managed_base") or "0"),
        "duplicate_open_d3_exit_detected": bool(review_report.get("duplicate_open_d3_exit_detected")),
        "oversell_detected": bool(review_report.get("oversell_detected")),
        "reservation_covers_remaining_size": Decimal(str(review_report.get("reserved_base_open_exit_orders") or "0")) >= Decimal(str(review_report.get("local_order_remaining_size") or "0")),
        "position_open_and_manageable": str(review_report.get("local_position_status") or "").strip().lower() == "open" and Decimal(str(review_report.get("position_size_base") or "0")) > Decimal("0"),
        "candidate_size_within_position": Decimal(str(review_report.get("local_order_remaining_size") or "0")) <= (
            Decimal(str(review_report.get("position_size_base") or "0")) +
            Decimal(str(review_report.get("reserved_base_open_exit_orders") or "0"))
        ),
        "coinbase_normalized_status": str(review_report.get("coinbase_normalized_status") or ""),
        "coinbase_filled_base": str(review_report.get("coinbase_filled_base") or "0"),
        "coinbase_filled_quote": str(review_report.get("coinbase_filled_quote") or "0"),
        "coinbase_avg_fill_price": str(review_report.get("coinbase_avg_fill_price") or "0"),
        "coinbase_fill_count": int(review_report.get("coinbase_fill_count") or 0),
        "coinbase_remaining_size": str(review_report.get("coinbase_remaining_size") or "0"),
        "coinbase_evidence_hash": str(review_report.get("coinbase_evidence_hash") or ""),
        "coinbase_lookup_methods_attempted": list(review_report.get("coinbase_lookup_methods_attempted") or []),
        "coinbase_lookup_failed_methods": list(review_report.get("coinbase_lookup_failed_methods") or []),
        "coinbase_lookup_succeeded_method": str(review_report.get("coinbase_lookup_succeeded_method") or ""),
        "coinbase_errors": dict(review_report.get("coinbase_errors") or {}),
        "coinbase_error_type": str((review_report.get("coinbase_errors") or {}).get("type") or ""),
        "coinbase_error_message": str((review_report.get("coinbase_errors") or {}).get("message") or ""),
        "coinbase_error_stage": str((review_report.get("coinbase_errors") or {}).get("stage") or ""),
        "order_id_used": str(review_report.get("order_id_used") or ""),
        "client_order_id_used": str(review_report.get("client_order_id_used") or ""),
        "product_id_used": str(review_report.get("product_id_used") or ""),
        "include_fills": bool(review_report.get("include_fills", False)),
        "raw_response_shape": dict(review_report.get("raw_response_shape") or {}),
        "fallback_attempted": len(review_report.get("coinbase_lookup_methods_attempted") or []) > 1,
        "fallback_succeeded": str(review_report.get("coinbase_lookup_succeeded_method") or "") != "get_order_by_exchange_order_id"
        and bool(review_report.get("coinbase_lookup_succeeded_method")),
        "coinbase_warnings": list(review_report.get("coinbase_warnings") or []),
        "preflight_status": decision["preflight_status"],
        "preflight_decision": decision["preflight_decision"],
        "preflight_reason": decision["preflight_reason"],
        "pilot_candidate_ready": bool(decision["pilot_candidate_ready"]),
        "cancel_leg_ready": bool(decision["cancel_leg_ready"]),
        "replace_leg_ready": bool(decision["replace_leg_ready"]),
        "candidate_cancel_order_id": decision["candidate_cancel_order_id"],
        "candidate_cancel_client_order_id": decision["candidate_cancel_client_order_id"],
        "candidate_replace_side": decision["candidate_replace_side"],
        "candidate_replace_size_base": decision["candidate_replace_size_base"],
        "candidate_replace_limit_price": decision["candidate_replace_limit_price"],
        "candidate_replace_post_only": bool(decision["candidate_replace_post_only"]),
        "candidate_replace_reduce_only_semantic": bool(decision["candidate_replace_reduce_only_semantic"]),
        "candidate_replace_requires_fresh_price": bool(decision["candidate_replace_requires_fresh_price"]),
        "candidate_replace_price_source": decision["candidate_replace_price_source"],
        "required_ack_for_future_pilot": decision["required_ack_for_future_pilot"],
        "next_allowed_action": decision["next_allowed_action"],
        "next_forbidden_actions": decision["next_forbidden_actions"],
        "requires_human_approval": bool(decision["requires_human_approval"]),
        "blockers": decision["blockers"],
        "warnings": decision["warnings"],
    }
    return _json_safe(report)


__all__ = [
    "D3_CANCEL_REPLACE_PILOT_PREFLIGHT_PHASE",
    "build_phase_d3_cancel_replace_pilot_preflight_report",
]
