from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from bot.order_store import FINAL_ORDER_STATUSES, OPEN_ORDER_STATUSES, OrderStore
from bot.state_store import StateStore

D3_LIVE_EXIT_RECONCILE_ACK = "I_UNDERSTAND_AND_APPROVE_D3_LIVE_EXIT_RECONCILIATION_APPLY"
ZERO = Decimal("0")


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


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _find_local_order(
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
            return order

    for order in store.all_orders():
        if selected_ticker and _normalize_ticker(order.get("ticker")) != selected_ticker:
            continue
        order_exchange_id = str(order.get("exchange_order_id") or order.get("order_id") or "").strip()
        if selected_exchange and order_exchange_id == selected_exchange:
            return dict(order)
    return None


def _count_duplicate_open_d3_orders(
    store: OrderStore,
    *,
    ticker: str,
    linked_position_id: str,
    exit_label: str,
    ignore_client_order_id: str,
) -> int:
    selected_ticker = _normalize_ticker(ticker)
    selected_position = str(linked_position_id or "").strip()
    selected_label = str(exit_label or "").strip().upper()
    duplicates = 0
    for order in store.open_exit_orders(ticker=selected_ticker or None):
        if str(order.get("client_order_id") or "").strip() == ignore_client_order_id:
            continue
        if str(order.get("linked_position_id") or "").strip() != selected_position:
            continue
        if str(order.get("d3_exit_label") or "").strip().upper() != selected_label:
            continue
        duplicates += 1
    return duplicates


def _snapshot_status(snapshot: Dict[str, Any]) -> str:
    return str(snapshot.get("normalized_status") or "").strip().lower()


def _status_to_action(status: str) -> str:
    if status == "open":
        return "keep_open"
    if status == "partially_filled":
        return "mark_partially_filled"
    if status == "filled":
        return "mark_filled"
    if status == "rejected":
        return "mark_rejected"
    if status in {"cancelled", "expired"}:
        return f"mark_{status}"
    return "unknown_no_apply"


def _position_base(position: Dict[str, Any]) -> Decimal:
    return _to_decimal(position.get("position_size_base"), "0")


def _position_quote(position: Dict[str, Any]) -> Decimal:
    return _to_decimal(position.get("position_size_quote"), "0")


def _bot_managed_base(position: Dict[str, Any]) -> Decimal:
    return _to_decimal(position.get("bot_managed_base"), "0")


def _order_size(local_order: Dict[str, Any]) -> Decimal:
    return _to_decimal(local_order.get("size_base"), "0")


def _local_filled_base(local_order: Dict[str, Any]) -> Decimal:
    return _to_decimal(local_order.get("filled_size") or local_order.get("filled_base"), "0")


def _local_filled_quote(local_order: Dict[str, Any]) -> Decimal:
    return _to_decimal(local_order.get("filled_quote_value") or local_order.get("filled_quote"), "0")


def _local_fees(local_order: Dict[str, Any]) -> Decimal:
    return _to_decimal(local_order.get("fees_paid") or local_order.get("fees"), "0")


def _reserved_base_for_other_open_exit_orders(
    store: OrderStore,
    *,
    ticker: str,
    linked_position_id: str,
    ignore_client_order_id: str,
) -> Decimal:
    selected_ticker = _normalize_ticker(ticker)
    selected_position = str(linked_position_id or "").strip()
    ignored_client = str(ignore_client_order_id or "").strip()
    reserved = ZERO
    for order in store.open_exit_orders(ticker=selected_ticker or None):
        if str(order.get("client_order_id") or "").strip() == ignored_client:
            continue
        if str(order.get("linked_position_id") or "").strip() != selected_position:
            continue
        reserved += max(ZERO, _to_decimal(order.get("remaining_size") or order.get("size_base"), "0"))
    return reserved


def _compute_total_managed_base_for_exit(
    *,
    position_base: Decimal,
    bot_managed_base: Decimal,
    reserved_base_this_exit: Decimal,
    reserved_base_other_open_exits: Decimal,
) -> Decimal:
    base_floor = max(ZERO, position_base, bot_managed_base)
    if bot_managed_base <= position_base:
        return base_floor
    return max(
        base_floor,
        position_base + max(ZERO, reserved_base_this_exit) + max(ZERO, reserved_base_other_open_exits),
    )


def _safety_envelope() -> Dict[str, Any]:
    return {
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "no_state_write": True,
        "default_mode": "dry_run",
    }


def reconcile_phase_d3_live_exit_order(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    snapshot: Dict[str, Any],
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    apply: bool = False,
    apply_ack: str = "",
) -> Dict[str, Any]:
    store = order_store or OrderStore()
    positions = state_store or StateStore()
    selected_ticker = _normalize_ticker(ticker)
    selected_client_id = str(client_order_id or "").strip()
    selected_exchange_id = str(exchange_order_id or "").strip()
    selected_position_id = str(linked_position_id or "").strip()
    local_order = _find_local_order(
        store,
        ticker=selected_ticker,
        client_order_id=selected_client_id,
        exchange_order_id=selected_exchange_id,
    )
    position = positions.get_position(selected_ticker) or {}
    now = _now_iso()

    report: Dict[str, Any] = {
        "generated_at": now,
        "ticker": selected_ticker,
        "client_order_id": selected_client_id,
        "exchange_order_id": selected_exchange_id,
        "linked_position_id": selected_position_id,
        "apply_requested": bool(apply),
        "apply_ack_present": bool(apply_ack),
        "no_state_write": True,
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "coinbase_snapshot": _json_safe(snapshot),
        "blockers": [],
        "warnings": [],
        "suggested_action": "unknown_no_apply",
        "proposed_order_updates": {},
        "proposed_position_updates": {},
        "status": "d3_live_exit_reconcile_blocked",
    }

    if not selected_exchange_id:
        report["blockers"].append("exchange_order_id_missing")
    if not isinstance(local_order, dict):
        report["blockers"].append("local_d3_order_not_found")
        return _json_safe(report)

    local_client_id = str(local_order.get("client_order_id") or "").strip()
    local_exchange_id = str(local_order.get("exchange_order_id") or local_order.get("order_id") or "").strip()
    local_position_id = str(local_order.get("linked_position_id") or "").strip()
    local_ticker = _normalize_ticker(local_order.get("ticker"))
    local_exit_label = str(local_order.get("d3_exit_label") or "").strip().upper()
    local_status = str(local_order.get("status") or "").strip().lower()

    if selected_client_id and local_client_id != selected_client_id:
        report["blockers"].append("client_order_id_mismatch")
    if selected_exchange_id and local_exchange_id != selected_exchange_id:
        report["blockers"].append("exchange_order_id_mismatch")
    if selected_position_id and local_position_id != selected_position_id:
        report["blockers"].append("linked_position_id_mismatch")
    if selected_ticker and local_ticker != selected_ticker:
        report["blockers"].append("ticker_mismatch")

    duplicates = _count_duplicate_open_d3_orders(
        store,
        ticker=selected_ticker,
        linked_position_id=local_position_id,
        exit_label=local_exit_label,
        ignore_client_order_id=local_client_id,
    )
    if duplicates > 0:
        report["blockers"].append("duplicate_open_d3_exit_order_for_position_and_label")

    snapshot_status = _snapshot_status(snapshot)
    report["suggested_action"] = _status_to_action(snapshot_status)
    report["local_order_status"] = local_status
    report["snapshot_status"] = snapshot_status

    if not snapshot.get("coinbase_call_succeeded", True):
        report["blockers"].append("coinbase_snapshot_unavailable")
    if snapshot_status in {"", "unknown", "cancel_pending"}:
        report["blockers"].append("coinbase_snapshot_status_unknown_or_unsupported")

    if report["blockers"]:
        return _json_safe(report)

    if local_status in FINAL_ORDER_STATUSES and snapshot_status == local_status:
        report["status"] = "d3_live_exit_reconcile_already_final"
        report["blockers"].append("local_order_already_finalized")
        return _json_safe(report)

    if snapshot_status == "open":
        report["status"] = "d3_live_exit_reconcile_keep_open"
        if apply:
            report["blockers"].append("d3_reconcile_open_order_no_apply_needed")
            report["status"] = "d3_live_exit_reconcile_apply_blocked"
        return _json_safe(report)

    if apply and str(apply_ack or "").strip() != D3_LIVE_EXIT_RECONCILE_ACK:
        report["blockers"].append("d3_live_exit_reconcile_apply_ack_required")
        return _json_safe(report)

    original_size = _order_size(local_order)
    snapshot_filled_base = _to_decimal(snapshot.get("filled_base"), "0")
    snapshot_filled_quote = _to_decimal(snapshot.get("filled_quote"), "0")
    snapshot_avg_fill_price = _to_decimal(snapshot.get("avg_fill_price"), "0")
    snapshot_fees = _to_decimal(snapshot.get("fees"), "0")
    local_filled_base = _local_filled_base(local_order)
    local_filled_quote = _local_filled_quote(local_order)
    local_fees = _local_fees(local_order)
    fill_delta_base = snapshot_filled_base - local_filled_base
    fill_delta_quote = snapshot_filled_quote - local_filled_quote
    fill_delta_fees = snapshot_fees - local_fees

    if snapshot_status in {"partially_filled", "filled"}:
        if snapshot_filled_base <= ZERO:
            report["blockers"].append("missing_fill_evidence_for_filled_or_partial_snapshot")
        if snapshot_filled_base > original_size:
            report["blockers"].append("filled_base_exceeds_order_size")
        if fill_delta_base < ZERO:
            report["blockers"].append("snapshot_filled_base_less_than_local_filled_base")
        if fill_delta_quote < ZERO:
            report["blockers"].append("snapshot_filled_quote_less_than_local_filled_quote")
        if fill_delta_fees < ZERO:
            report["blockers"].append("snapshot_fees_less_than_local_fees")

    if report["blockers"]:
        return _json_safe(report)

    remaining_size = max(ZERO, original_size - snapshot_filled_base)
    if snapshot_status == "partially_filled" and remaining_size <= ZERO:
        report["warnings"].append("partial_snapshot_has_zero_remaining_size")

    order_updates: Dict[str, Any] = {
        "exchange_order_id": local_exchange_id,
        "order_id": local_exchange_id,
        "last_coinbase_snapshot_status": snapshot_status,
        "last_coinbase_snapshot_raw_status": str(snapshot.get("raw_status") or ""),
        "last_reconciled_at": now,
        "filled_size": str(snapshot_filled_base),
        "filled_base": str(snapshot_filled_base),
        "filled_quote_value": str(snapshot_filled_quote),
        "filled_quote": str(snapshot_filled_quote),
        "avg_fill_price": str(snapshot_avg_fill_price),
        "fill_count": int(snapshot.get("fill_count") or 0),
        "fees_paid": str(snapshot_fees),
        "liquidity": snapshot.get("liquidity") or [],
    }
    position_updates: Dict[str, Any] = {
        "last_d3_reconcile_at": now,
        "last_d3_reconcile_client_order_id": local_client_id,
        "last_d3_reconcile_exchange_order_id": local_exchange_id,
        "last_d3_reconcile_status": snapshot_status,
        "last_d3_reconcile_action": report["suggested_action"],
    }

    if snapshot_status == "rejected":
        order_updates.update({
            "status": "rejected",
            "remaining_size": "0",
            "remaining_quote": "0",
            "rejected_at": now,
            "finalized_at": now,
            "closed_at": now,
            "reject_reason": str(snapshot.get("raw_status") or "rejected"),
        })
        report["status"] = "d3_live_exit_reconcile_rejected_ready"
    elif snapshot_status in {"cancelled", "expired"}:
        order_updates.update({
            "status": snapshot_status,
            "remaining_size": "0",
            "remaining_quote": "0",
            "finalized_at": now,
            "closed_at": now,
            f"{snapshot_status}_at": now,
        })
        report["status"] = f"d3_live_exit_reconcile_{snapshot_status}_ready"
    elif snapshot_status in {"partially_filled", "filled"}:
        position_base = _position_base(position)
        bot_base = _bot_managed_base(position)
        position_quote = _position_quote(position)
        reserved_base_this_exit = _to_decimal(local_order.get("remaining_size") or local_order.get("size_base"), "0")
        reserved_base_other_open_exits = _reserved_base_for_other_open_exit_orders(
            store,
            ticker=selected_ticker,
            linked_position_id=local_position_id,
            ignore_client_order_id=local_client_id,
        )
        total_managed_base = _compute_total_managed_base_for_exit(
            position_base=position_base,
            bot_managed_base=bot_base,
            reserved_base_this_exit=reserved_base_this_exit,
            reserved_base_other_open_exits=reserved_base_other_open_exits,
        )
        if fill_delta_base > total_managed_base:
            report["blockers"].append("filled_base_exceeds_total_managed_base")
            return _json_safe(report)
        if fill_delta_base > reserved_base_this_exit:
            report["blockers"].append("filled_base_exceeds_remaining_open_exit_size")
            return _json_safe(report)

        resulting_bot_base = total_managed_base - fill_delta_base
        resulting_reserved_base_this_exit = remaining_size if snapshot_status == "partially_filled" else ZERO
        resulting_position_base = max(
            ZERO,
            resulting_bot_base - reserved_base_other_open_exits - resulting_reserved_base_this_exit,
        )
        if resulting_position_base < ZERO or resulting_bot_base < ZERO:
            report["blockers"].append("resulting_position_base_negative")
            return _json_safe(report)

        resulting_position_quote = max(ZERO, position_quote - max(ZERO, fill_delta_quote))
        order_updates.update({
            "status": "filled" if snapshot_status == "filled" else "partially_filled",
            "remaining_size": str(remaining_size if snapshot_status == "partially_filled" else ZERO),
            "remaining_quote": "0",
            "last_fill_delta_base": str(fill_delta_base),
            "last_fill_delta_quote": str(max(ZERO, fill_delta_quote)),
            "last_fill_delta_fees": str(max(ZERO, fill_delta_fees)),
        })
        if snapshot_status == "filled":
            order_updates.update({
                "filled_at": now,
                "finalized_at": now,
                "closed_at": now,
            })
            report["status"] = "d3_live_exit_reconcile_filled_ready"
        else:
            report["status"] = "d3_live_exit_reconcile_partially_filled_ready"

        position_updates.update({
            "position_size_base": str(resulting_position_base),
            "bot_managed_base": str(resulting_bot_base),
            "position_size_quote": str(resulting_position_quote),
            "last_d3_reconcile_fill_delta_base": str(fill_delta_base),
            "last_d3_reconcile_fill_delta_quote": str(max(ZERO, fill_delta_quote)),
            "last_d3_reconcile_fees_delta": str(max(ZERO, fill_delta_fees)),
            "last_d3_exit_label": local_exit_label,
            "last_d3_reconcile_total_managed_base_before_fill": str(total_managed_base),
            "last_d3_reconcile_reserved_base_other_open_exits": str(reserved_base_other_open_exits),
            "last_d3_reconcile_reserved_base_this_exit_before_fill": str(reserved_base_this_exit),
            "last_d3_reconcile_reserved_base_this_exit_after_fill": str(resulting_reserved_base_this_exit),
        })
        if snapshot_status == "filled":
            position_updates[f"d3_{local_exit_label.lower()}_completed_at"] = now
            position_updates[f"d3_{local_exit_label.lower()}_completed_order_id"] = local_exchange_id
            if resulting_position_base == ZERO:
                position_updates.update({
                    "status": "closed",
                    "close_time": now,
                    "close_reason": "d3_live_exit_order_filled_position_flattened",
                    "last_heartbeat_status": "closed",
                    "last_heartbeat_at": now,
                    "last_heartbeat_reason": "d3_live_exit_order_filled_position_flattened",
                    "monitoring_enabled": False,
                })
        else:
            position_updates["last_heartbeat_status"] = str(position.get("last_heartbeat_status") or "open")
    else:
        report["blockers"].append("coinbase_snapshot_status_unknown_or_unsupported")
        return _json_safe(report)

    report["proposed_order_updates"] = _json_safe(order_updates)
    report["proposed_position_updates"] = _json_safe(position_updates)

    if not apply:
        return _json_safe(report)

    applied_order = store.update_order(local_client_id, order_updates, event_type="d3_live_exit_reconciled")
    if applied_order is None:
        report["blockers"].append("local_d3_order_update_failed")
        report["status"] = "d3_live_exit_reconcile_apply_failed"
        return _json_safe(report)

    applied_position = position
    if position_updates:
        applied_position = positions.upsert_position(
            selected_ticker,
            position_updates,
            caller_reason="controlled_d3_lifecycle_apply",
            evidence_status=snapshot_status,
        )

    report["status"] = report["status"].replace("_ready", "_applied")
    report["no_state_write"] = False
    report["applied_order"] = _json_safe(applied_order)
    report["applied_position"] = _json_safe(applied_position)
    return _json_safe(report)


__all__ = [
    "D3_LIVE_EXIT_RECONCILE_ACK",
    "reconcile_phase_d3_live_exit_order",
]
