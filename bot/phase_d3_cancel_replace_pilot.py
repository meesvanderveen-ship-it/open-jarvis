from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from bot.live_exit_gate import assert_live_exit_allowed
from bot.order_store import OrderStore
from bot.phase_d3_cancel_replace_pilot_preflight import (
    D3_CANCEL_REPLACE_PILOT_ACK,
    build_phase_d3_cancel_replace_pilot_preflight_report,
)
from bot.phase_d3_open_exit_lifecycle_manager import order_matches_logical_position
from bot.state_store import StateStore


D3_CANCEL_REPLACE_PILOT_PHASE = "D3_cancel_replace_pilot"
D3_CANCEL_REPLACE_PILOT_SOURCE = "phase_d3_cancel_replace_pilot"
ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _next_replacement_client_order_id(*, ticker: str, linked_position_id: str) -> str:
    clean_ticker = _normalize_ticker(ticker).replace("-", "")
    pos_suffix = str(linked_position_id or "pos")[-8:].replace("-", "")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"phased3-{clean_ticker}-TP1-repl-{pos_suffix}-{timestamp}"


def _find_matching_order(store: OrderStore, *, client_order_id: str, exchange_order_id: str, linked_position_id: str) -> Dict[str, Any]:
    for order in store.all_orders():
        if str(order.get("client_order_id") or "").strip() != str(client_order_id or "").strip():
            continue
        if str(order.get("exchange_order_id") or order.get("order_id") or "").strip() != str(exchange_order_id or "").strip():
            continue
        if linked_position_id and not order_matches_logical_position(order, linked_position_id=linked_position_id):
            continue
        return dict(order)
    return {}


def _find_existing_replacement(store: OrderStore, *, original_client_order_id: str, original_exchange_order_id: str, linked_position_id: str) -> Dict[str, Any]:
    for order in store.all_orders():
        if str(order.get("replacement_of_client_order_id") or "").strip() != str(original_client_order_id or "").strip():
            continue
        if str(order.get("replacement_of_exchange_order_id") or "").strip() != str(original_exchange_order_id or "").strip():
            continue
        if linked_position_id and not order_matches_logical_position(order, linked_position_id=linked_position_id):
            continue
        return dict(order)
    return {}


def _count_open_d3_exit_orders(store: OrderStore, *, ticker: str, linked_position_id: str) -> int:
    count = 0
    for order in store.open_exit_orders(ticker=ticker):
        if linked_position_id and not order_matches_logical_position(order, linked_position_id=linked_position_id):
            continue
        count += 1
    return count


def _min_size_and_quote_from_position(position: Dict[str, Any]) -> Dict[str, Decimal]:
    return {
        "min_size": _to_decimal(
            position.get("effective_min_trade_base")
            or position.get("exchange_base_min_size")
            or "0",
            "0",
        ),
        "min_quote": _to_decimal(
            position.get("exchange_quote_min_size")
            or position.get("min_order_quote")
            or "1",
            "1",
        ),
    }


def _normalize_cancel_result(payload: Any, *, order_id: str) -> Dict[str, Any]:
    data = _as_dict(payload)
    # Coinbase's real batch_cancel response is
    # {"results": [{"success": bool, "order_id": ..., "failure_reason": ...}]},
    # not a flat success_results/order_ids/cancelled_order_ids list (see
    # bot/controlled_stop_market_exit_plan.py for the live incident this
    # exact mismatch caused). Check the real shape first.
    results = data.get("results") if isinstance(data.get("results"), list) else []
    for item in results:
        if not isinstance(item, dict):
            continue
        if order_id and str(item.get("order_id") or "").strip() != order_id:
            continue
        if bool(item.get("success")):
            return {
                "cancel_succeeded": True,
                "cancel_raw_status": "BATCH_CANCELLED",
                "cancel_normalized_status": "cancelled",
                "cancel_error_type": "",
                "cancel_error_message": "",
            }
        return {
            "cancel_succeeded": False,
            "cancel_raw_status": str(item.get("failure_reason") or "").strip().upper(),
            "cancel_normalized_status": "unknown",
            "cancel_error_type": "RuntimeError",
            "cancel_error_message": str(item.get("failure_reason") or "cancel_response_not_confirmed"),
        }

    order_ids = [str(item).strip() for item in (data.get("success_results") or data.get("order_ids") or data.get("cancelled_order_ids") or []) if str(item).strip()]
    if order_id and order_id in order_ids:
        return {
            "cancel_succeeded": True,
            "cancel_raw_status": "BATCH_CANCELLED",
            "cancel_normalized_status": "cancelled",
            "cancel_error_type": "",
            "cancel_error_message": "",
        }

    raw_status = str(
        data.get("status")
        or data.get("order_status")
        or data.get("result")
        or data.get("success")
        or ""
    ).strip().upper()
    normalized = ""
    if raw_status in {"CANCELLED", "CANCELED"}:
        normalized = "cancelled"
    elif raw_status in {"CANCEL_PENDING", "PENDING_CANCEL"}:
        normalized = "cancel_pending"
    elif raw_status in {"OPEN", "SUBMITTED"}:
        normalized = "open"
    success = bool(data.get("success", False)) and normalized in {"cancelled", "cancel_pending"}
    return {
        "cancel_succeeded": success,
        "cancel_raw_status": raw_status,
        "cancel_normalized_status": normalized or "unknown",
        "cancel_error_type": "" if success else "RuntimeError",
        "cancel_error_message": "" if success else "cancel_response_not_confirmed",
    }


def _normalize_replace_result(payload: Any) -> Dict[str, Any]:
    data = _as_dict(payload)
    success = bool(data.get("success", True))
    success_response = _as_dict(data.get("success_response"))
    error_response = _as_dict(data.get("error_response"))
    order_id = str(data.get("order_id") or data.get("id") or success_response.get("order_id") or "").strip()
    raw_status = str(
        data.get("status")
        or data.get("order_status")
        or success_response.get("status")
        or ""
    ).strip().upper()
    normalized = "submitted" if success and order_id else "unknown"
    error_message = ""
    if not success or not order_id:
        error_message = str(
            error_response.get("message")
            or error_response.get("error")
            or "replacement_submit_unconfirmed"
        )
    return {
        "replace_succeeded": bool(success and order_id),
        "replace_exchange_order_id": order_id,
        "replace_raw_status": raw_status,
        "replace_normalized_status": normalized,
        "replace_error_type": "" if success and order_id else "RuntimeError",
        "replace_error_message": error_message,
    }


def run_phase_d3_cancel_replace_pilot(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    cfg: Any = None,
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    allow_coinbase_poll: bool = False,
    allow_live_cancel: bool = False,
    allow_live_replace: bool = False,
    pilot_ack: str = "",
    snapshot: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    store = order_store or OrderStore()
    states = state_store or StateStore()
    selected_ticker = _normalize_ticker(ticker)
    matching_order = _find_matching_order(
        store,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        linked_position_id=linked_position_id,
    )
    existing_replacement = _find_existing_replacement(
        store,
        original_client_order_id=client_order_id,
        original_exchange_order_id=exchange_order_id,
        linked_position_id=linked_position_id,
    )
    position = states.get_position(selected_ticker) or {}
    preflight = build_phase_d3_cancel_replace_pilot_preflight_report(
        ticker=selected_ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        linked_position_id=linked_position_id,
        order_store=store,
        state_store=states,
        coinbase_client=coinbase_client,
        allow_coinbase_poll=allow_coinbase_poll,
        snapshot=snapshot,
        now=now,
    )

    required_ack = str(preflight.get("required_ack_for_future_pilot") or D3_CANCEL_REPLACE_PILOT_ACK)
    ack_valid = str(pilot_ack or "").strip() == required_ack
    preflight_ready = str(preflight.get("status") or "") == "cancel_replace_pilot_preflight_ready"
    live_flags_present = bool(allow_coinbase_poll and allow_live_cancel and allow_live_replace)
    armed_live = bool(live_flags_present and ack_valid)
    remaining_size = str(preflight.get("candidate_replace_size_base") or preflight.get("local_order_remaining_size") or "0")
    limit_price = str(preflight.get("candidate_replace_limit_price") or "")
    open_count_after = _count_open_d3_exit_orders(store, ticker=selected_ticker, linked_position_id=linked_position_id)

    report: Dict[str, Any] = {
        "status": "cancel_replace_pilot_preview_blocked",
        "phase": D3_CANCEL_REPLACE_PILOT_PHASE,
        "ticker": selected_ticker,
        "client_order_id": str(client_order_id or "").strip(),
        "exchange_order_id": str(exchange_order_id or "").strip(),
        "linked_position_id": str(linked_position_id or "").strip(),
        "generated_at": _now_iso(),
        "mode": "armed_live_pilot" if armed_live else "preview",
        "state_write_performed": False,
        "coinbase_call_attempted": bool(preflight.get("coinbase_call_attempted")),
        "coinbase_call_succeeded": bool(preflight.get("coinbase_call_succeeded")),
        "coinbase_error_type": str(preflight.get("coinbase_error_type") or ""),
        "coinbase_error_message": str(preflight.get("coinbase_error_message") or ""),
        "coinbase_error_stage": str(preflight.get("coinbase_error_stage") or ""),
        "coinbase_lookup_methods_attempted": list(preflight.get("coinbase_lookup_methods_attempted") or []),
        "coinbase_lookup_succeeded_method": str(preflight.get("coinbase_lookup_succeeded_method") or ""),
        "coinbase_lookup_failed_methods": list(preflight.get("coinbase_lookup_failed_methods") or []),
        "order_id_used": str(preflight.get("order_id_used") or ""),
        "client_order_id_used": str(preflight.get("client_order_id_used") or ""),
        "product_id_used": str(preflight.get("product_id_used") or ""),
        "include_fills": bool(preflight.get("include_fills", False)),
        "fallback_attempted": bool(preflight.get("fallback_attempted")),
        "fallback_succeeded": bool(preflight.get("fallback_succeeded")),
        "raw_response_shape": dict(preflight.get("raw_response_shape") or {}),
        "coinbase_cancel_attempted": False,
        "coinbase_cancel_succeeded": False,
        "coinbase_replace_attempted": False,
        "coinbase_replace_succeeded": False,
        "live_action_performed": False,
        "no_unapproved_coinbase_cancel": not ack_valid or not allow_live_cancel,
        "no_unapproved_coinbase_replace": not ack_valid or not allow_live_replace,
        "no_unapproved_coinbase_submit": not ack_valid or not allow_live_replace,
        "preflight_status": str(preflight.get("status") or ""),
        "preflight_decision": str(preflight.get("preflight_decision") or ""),
        "pilot_candidate_ready": bool(preflight.get("pilot_candidate_ready")),
        "cancel_leg_ready": bool(preflight.get("cancel_leg_ready")),
        "replace_leg_ready": bool(preflight.get("replace_leg_ready")),
        "required_ack": required_ack,
        "ack_valid": ack_valid,
        "blockers": list(preflight.get("blockers") or []),
        "warnings": list(preflight.get("warnings") or []),
        "cancel_candidate_order_id": str(preflight.get("candidate_cancel_order_id") or exchange_order_id or ""),
        "cancel_candidate_client_order_id": str(preflight.get("candidate_cancel_client_order_id") or client_order_id or ""),
        "cancel_allowed": bool(preflight.get("cancel_leg_ready")),
        "cancel_attempted": False,
        "cancel_succeeded": False,
        "cancel_raw_status": "",
        "cancel_normalized_status": "",
        "cancel_error_type": "",
        "cancel_error_message": "",
        "cancel_state_update_required": False,
        "cancel_state_update_performed": False,
        "replace_allowed": bool(preflight.get("replace_leg_ready")),
        "replace_attempted": False,
        "replace_succeeded": False,
        "replace_side": str(preflight.get("candidate_replace_side") or "SELL"),
        "replace_size_base": remaining_size,
        "replace_limit_price": limit_price,
        "replace_post_only": bool(preflight.get("candidate_replace_post_only", True)),
        "replace_reduce_only_semantic": bool(preflight.get("candidate_replace_reduce_only_semantic", True)),
        "replace_client_order_id": "",
        "replace_exchange_order_id": "",
        "replace_raw_status": "",
        "replace_normalized_status": "",
        "replace_error_type": "",
        "replace_error_message": "",
        "replace_state_update_required": False,
        "replace_state_update_performed": False,
        "local_old_order_status_before": str(matching_order.get("status") or ""),
        "local_old_order_status_after": str(matching_order.get("status") or ""),
        "local_new_order_status_after": str(existing_replacement.get("status") or ""),
        "local_position_status_after": str(position.get("status") or ""),
        "position_size_base_after": str(position.get("position_size_base") or "0"),
        "reserved_base_open_exit_orders_after": str(position.get("reserved_base_open_exit_orders") or "0"),
        "bot_managed_base_after": str(position.get("bot_managed_base") or "0"),
        "open_d3_exit_count_after": open_count_after,
        "duplicate_open_d3_exit_detected_after": open_count_after > 1,
        "oversell_detected_after": bool(preflight.get("oversell_detected")),
        "pilot_decision": "blocked_review_required",
        "next_allowed_action": str(preflight.get("next_allowed_action") or ""),
        "next_forbidden_actions": list(preflight.get("next_forbidden_actions") or []),
        "requires_human_review": True,
        "priority_classification": str(preflight.get("priority_classification") or "P1"),
    }

    if existing_replacement:
        report.update({
            "status": "cancel_replace_pilot_already_applied_noop",
            "pilot_decision": "replacement_order_already_present_noop",
            "replace_client_order_id": str(existing_replacement.get("client_order_id") or ""),
            "replace_exchange_order_id": str(existing_replacement.get("exchange_order_id") or existing_replacement.get("order_id") or ""),
            "local_new_order_status_after": str(existing_replacement.get("status") or ""),
            "requires_human_review": False,
        })
        return _json_safe(report)

    if not preflight_ready:
        report.update({
            "status": "cancel_replace_pilot_preview_blocked",
            "pilot_decision": "preflight_not_ready",
        })
        return _json_safe(report)

    if not live_flags_present and not pilot_ack:
        report.update({
            "status": "cancel_replace_pilot_preview_ready",
            "pilot_decision": "await_explicit_ack_for_live_cancel_replace_pilot",
            "cancel_allowed": True,
            "replace_allowed": True,
            "requires_human_review": True,
        })
        return _json_safe(report)

    if not ack_valid:
        report.update({
            "status": "cancel_replace_pilot_blocked_ack_required",
            "pilot_decision": "ack_required_or_invalid",
            "requires_human_review": True,
        })
        return _json_safe(report)

    if not live_flags_present:
        report.update({
            "status": "cancel_replace_pilot_preview_blocked",
            "pilot_decision": "required_live_flags_missing",
            "blockers": sorted(set(report["blockers"] + ["pilot_live_flags_missing"])),
        })
        return _json_safe(report)

    if coinbase_client is None:
        report.update({
            "status": "cancel_replace_pilot_preview_blocked",
            "pilot_decision": "coinbase_client_missing",
            "blockers": sorted(set(report["blockers"] + ["coinbase_client_missing"])),
        })
        return _json_safe(report)

    if str(preflight.get("coinbase_normalized_status") or "").strip().lower() != "open":
        report.update({
            "status": "cancel_replace_pilot_preview_blocked",
            "pilot_decision": "coinbase_open_evidence_required",
            "blockers": sorted(set(report["blockers"] + ["coinbase_open_evidence_required"])),
        })
        return _json_safe(report)

    min_rules = _min_size_and_quote_from_position(position)
    replace_size = _to_decimal(remaining_size, "0")
    replace_limit = _to_decimal(limit_price, "0")
    replace_quote = replace_size * replace_limit if replace_size > ZERO and replace_limit > ZERO else ZERO
    if replace_size <= ZERO:
        report.update({
            "status": "cancel_replace_pilot_preview_blocked",
            "pilot_decision": "replacement_size_invalid",
            "blockers": sorted(set(report["blockers"] + ["replacement_size_invalid"])),
        })
        return _json_safe(report)
    if min_rules["min_size"] > ZERO and replace_size < min_rules["min_size"]:
        report.update({
            "status": "cancel_replace_pilot_preview_blocked",
            "pilot_decision": "replacement_below_min_size",
            "blockers": sorted(set(report["blockers"] + ["replacement_below_min_size"])),
        })
        return _json_safe(report)
    if min_rules["min_quote"] > ZERO and replace_quote < min_rules["min_quote"]:
        report.update({
            "status": "cancel_replace_pilot_preview_blocked",
            "pilot_decision": "replacement_below_min_quote",
            "blockers": sorted(set(report["blockers"] + ["replacement_below_min_quote"])),
        })
        return _json_safe(report)

    report["coinbase_cancel_attempted"] = True
    report["cancel_attempted"] = True
    report["live_action_performed"] = True
    try:
        cancel_response = coinbase_client.cancel_order(order_id=exchange_order_id)
        report["coinbase_call_attempted"] = True
        report["coinbase_call_succeeded"] = True
        cancel_result = _normalize_cancel_result(cancel_response, order_id=exchange_order_id)
        report.update(cancel_result)
        report["coinbase_cancel_succeeded"] = bool(cancel_result["cancel_succeeded"])
        report["cancel_succeeded"] = bool(cancel_result["cancel_succeeded"])
    except Exception as exc:
        report.update({
            "status": "cancel_replace_pilot_cancel_failed_no_replace",
            "pilot_decision": "cancel_failed_no_replace",
            "cancel_error_type": type(exc).__name__,
            "cancel_error_message": str(exc),
            "requires_human_review": True,
        })
        return _json_safe(report)

    if not report["cancel_succeeded"]:
        report.update({
            "status": "cancel_replace_pilot_cancel_uncertain_no_replace",
            "pilot_decision": "cancel_uncertain_manual_review_required",
            "requires_human_review": True,
        })
        return _json_safe(report)

    gate = assert_live_exit_allowed(
        cfg=cfg,
        side="SELL",
        source_module="bot.phase_d3_cancel_replace_pilot",
        source_function="run_phase_d3_cancel_replace_pilot",
        source_tag=D3_CANCEL_REPLACE_PILOT_SOURCE,
        intended_exit_type="limit_sell_replacement",
        ticker=selected_ticker,
        client_order_id=client_order_id,
        order_id=exchange_order_id,
        local_position_id=linked_position_id,
        reason="D3_CANCEL_REPLACE_PILOT",
        close_reason="D3_CANCEL_REPLACE_PILOT",
        execution_status="cancel_replace_replacement_submit_attempted",
        human_ack=pilot_ack,
        required_human_ack=required_ack,
        allowed_sources={D3_CANCEL_REPLACE_PILOT_SOURCE},
    )
    report["coinbase_replace_attempted"] = True
    report["replace_attempted"] = True
    replacement_client_order_id = _next_replacement_client_order_id(
        ticker=selected_ticker,
        linked_position_id=linked_position_id,
    )
    report["replace_client_order_id"] = replacement_client_order_id
    try:
        replace_response = coinbase_client.place_limit_order(
            ticker=selected_ticker,
            side="SELL",
            base_size=replace_size,
            limit_price=replace_limit,
            client_order_id=replacement_client_order_id,
            post_only=True,
        )
        replace_result = _normalize_replace_result(replace_response)
        report.update(replace_result)
        report["coinbase_replace_succeeded"] = bool(replace_result["replace_succeeded"])
        report["replace_succeeded"] = bool(replace_result["replace_succeeded"])
    except Exception as exc:
        report.update({
            "status": "cancel_replace_pilot_replace_failed_manual_review_required",
            "pilot_decision": "replace_failed_manual_review_required",
            "replace_error_type": type(exc).__name__,
            "replace_error_message": str(exc),
            "requires_human_review": True,
            "coinbase_replace_succeeded": False,
            "replace_succeeded": False,
        })
        return _json_safe(report)

    if not report["replace_succeeded"]:
        report.update({
            "status": "cancel_replace_pilot_replace_failed_manual_review_required",
            "pilot_decision": "replace_failed_manual_review_required",
            "requires_human_review": True,
        })
        return _json_safe(report)

    now_iso = _now_iso()
    store.update_order(
        client_order_id,
        {
            "status": "cancelled",
            "finalized_at": now_iso,
            "closed_at": now_iso,
            "cancelled_at": now_iso,
            "cancel_replace_pilot_id": replacement_client_order_id,
        },
        event_type="phase_d3_cancel_replace_old_order_cancelled",
    )
    new_order = store.upsert_order(
        {
            "client_order_id": replacement_client_order_id,
            "exchange_order_id": report["replace_exchange_order_id"],
            "order_id": report["replace_exchange_order_id"],
            "ticker": selected_ticker,
            "product_id": selected_ticker,
            "side": "SELL",
            "status": "submitted",
            "mode": "live",
            "source_mode": D3_CANCEL_REPLACE_PILOT_SOURCE,
            "phase": D3_CANCEL_REPLACE_PILOT_PHASE,
            "created_at": now_iso,
            "submitted_at": now_iso,
            "size_base": remaining_size,
            "remaining_size": remaining_size,
            "filled_base": "0",
            "filled_quote": "0",
            "fill_count": 0,
            "limit_price": limit_price,
            "post_only": True,
            "execution_action": "place_limit_sell",
            "linked_position_id": linked_position_id,
            "reduce_only_local": True,
            "replacement_of_client_order_id": client_order_id,
            "replacement_of_exchange_order_id": exchange_order_id,
            "cancel_replace_pilot_id": replacement_client_order_id,
            "live_order_submitted": True,
        },
        event_type="phase_d3_cancel_replace_replacement_submitted",
    )
    states.upsert_position(
        selected_ticker,
        {
            "status": "open",
            "reserved_base_open_exit_orders": remaining_size,
            "bot_managed_base": str(position.get("bot_managed_base") or position.get("position_size_base") or "0"),
            "position_size_base": str(position.get("position_size_base") or "0"),
            "recovery_linked_position_id": linked_position_id,
            "last_cancel_replace_pilot_id": replacement_client_order_id,
            "last_cancel_replace_replaced_client_order_id": client_order_id,
            "last_cancel_replace_replaced_exchange_order_id": exchange_order_id,
        },
    )

    final_position = states.get_position(selected_ticker) or {}
    open_count_after = _count_open_d3_exit_orders(store, ticker=selected_ticker, linked_position_id=linked_position_id)
    report.update({
        "status": "cancel_replace_pilot_applied",
        "pilot_decision": "cancel_replace_pilot_applied",
        "state_write_performed": True,
        "cancel_state_update_required": True,
        "cancel_state_update_performed": True,
        "replace_state_update_required": True,
        "replace_state_update_performed": True,
        "local_old_order_status_after": "cancelled",
        "local_new_order_status_after": str(new_order.get("status") or ""),
        "local_position_status_after": str(final_position.get("status") or ""),
        "position_size_base_after": str(final_position.get("position_size_base") or "0"),
        "reserved_base_open_exit_orders_after": str(final_position.get("reserved_base_open_exit_orders") or "0"),
        "bot_managed_base_after": str(final_position.get("bot_managed_base") or "0"),
        "open_d3_exit_count_after": open_count_after,
        "duplicate_open_d3_exit_detected_after": open_count_after > 1,
        "oversell_detected_after": False,
        "requires_human_review": False,
        "live_exit_gate_evaluation": gate,
    })
    return _json_safe(report)


__all__ = [
    "D3_CANCEL_REPLACE_PILOT_PHASE",
    "run_phase_d3_cancel_replace_pilot",
]
