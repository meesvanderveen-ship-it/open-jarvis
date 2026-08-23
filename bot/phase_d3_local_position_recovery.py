from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.order_store import OPEN_ORDER_STATUSES, OrderStore
from bot.state_store import StateStore


PHASE_D3_LOCAL_POSITION_RECOVERY_PHASE = "D3_local_position_recovery"
PHASE_D3_LOCAL_POSITION_RECOVERY_ACK = (
    "I_UNDERSTAND_AND_APPROVE_D3_LOCAL_POSITION_RECOVERY_APPLY"
)
RECOVERY_REASON = "d3_open_exit_local_position_reconstruction_preview"
RECOVERY_SOURCE = "open_d3_exit_hold_mismatch"
RECOVERY_VALUES_SOURCE = "docs/D3_LOCAL_POSITION_RECONSTRUCTION_PREVIEW.md"
ZERO = Decimal("0")
SAFE_OPEN_ORDER_STATUSES = {"submitted", "open"}


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
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _env_flag_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _compute_changes(current: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    changes: Dict[str, Dict[str, Any]] = {}
    for key, new_value in updates.items():
        old_value = current.get(key)
        if old_value != new_value:
            changes[key] = {"before": _json_safe(old_value), "after": _json_safe(new_value)}
    return changes


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


def _matching_open_d3_orders(
    *,
    order_store: OrderStore,
    ticker: str,
    linked_position_id: str,
) -> List[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    selected_linked = str(linked_position_id or "").strip()
    matches: List[Dict[str, Any]] = []
    for order in order_store.open_exit_orders(ticker=selected_ticker):
        if str(order.get("linked_position_id") or "").strip() != selected_linked:
            continue
        if str(order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
            continue
        matches.append(dict(order))
    return matches


def _build_recovery_updates(
    position: Dict[str, Any],
    *,
    position_size_base: Decimal,
    reserved_base_open_exit_orders: Decimal,
    bot_managed_base: Decimal,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
) -> Dict[str, Any]:
    now = _now_iso()
    updates: Dict[str, Any] = {
        "status": "open",
        "position_size_base": str(position_size_base),
        "bot_managed_base": str(bot_managed_base),
        "monitoring_enabled": True,
        "last_heartbeat_status": "recovered_open_d3_exit_hold_mismatch",
        "last_heartbeat_reason": RECOVERY_REASON,
        "last_recovery_reason": RECOVERY_REASON,
        "recovery_reason": RECOVERY_REASON,
        "recovery_source": RECOVERY_SOURCE,
        "recovery_at": now,
        "recovered_at": now,
        "recovery_linked_d3_client_order_id": str(client_order_id or ""),
        "recovery_linked_d3_exchange_order_id": str(exchange_order_id or ""),
        "recovery_linked_position_id": str(linked_position_id or ""),
        "reserved_base_open_exit_orders": str(reserved_base_open_exit_orders),
        "recovery_preview_only": False,
        "recovery_preview_values_source": RECOVERY_VALUES_SOURCE,
    }

    historical_fields = (
        ("close_reason", "previous_close_reason"),
        ("synthetic_close_reason", "previous_synthetic_close_reason"),
        ("synthetic_closed_at", "previous_synthetic_closed_at"),
        ("closed_at", "previous_closed_at"),
        ("close_time", "previous_close_time"),
        ("close_reason", "historical_close_reason"),
        ("synthetic_close_reason", "historical_synthetic_close_reason"),
        ("synthetic_closed_at", "historical_synthetic_closed_at"),
        ("closed_at", "historical_closed_at"),
        ("close_time", "historical_close_time"),
    )
    for source_key, historical_key in historical_fields:
        if source_key in position and historical_key not in position:
            updates[historical_key] = position.get(source_key)

    if "last_heartbeat_status" in position:
        updates["previous_last_heartbeat_status"] = position.get("last_heartbeat_status")
    if "last_heartbeat_reason" in position:
        updates["previous_last_heartbeat_reason"] = position.get("last_heartbeat_reason")

    updates["close_reason"] = ""
    updates["synthetic_close_reason"] = ""
    updates["synthetic_closed_at"] = None
    updates["closed_at"] = None
    updates["close_time"] = None
    return updates


def build_phase_d3_local_position_recovery_report(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    position_size_base: Any,
    reserved_base_open_exit_orders: Any,
    bot_managed_base: Any,
    apply: bool = False,
    recovery_ack: str = "",
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    selected_client = str(client_order_id or "").strip()
    selected_exchange = str(exchange_order_id or "").strip()
    selected_linked = str(linked_position_id or "").strip()
    position_base = _to_decimal(position_size_base, "0")
    reserved_base = _to_decimal(reserved_base_open_exit_orders, "0")
    managed_base = _to_decimal(bot_managed_base, "0")
    store = order_store or OrderStore()
    positions = state_store or StateStore()
    position = positions.get_position(selected_ticker) or {}
    local_order = _find_local_order(
        store,
        ticker=selected_ticker,
        client_order_id=selected_client,
        exchange_order_id=selected_exchange,
    )
    open_d3_orders = _matching_open_d3_orders(
        order_store=store,
        ticker=selected_ticker,
        linked_position_id=selected_linked,
    )

    report: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "phase": PHASE_D3_LOCAL_POSITION_RECOVERY_PHASE,
        "ticker": selected_ticker,
        "client_order_id": selected_client,
        "exchange_order_id": selected_exchange,
        "linked_position_id": selected_linked,
        "apply_requested": bool(apply),
        "dry_run": not bool(apply),
        "required_recovery_ack": PHASE_D3_LOCAL_POSITION_RECOVERY_ACK,
        "recovery_ack_valid": not bool(apply) or str(recovery_ack or "").strip() == PHASE_D3_LOCAL_POSITION_RECOVERY_ACK,
        "no_state_write": True,
        "state_write_performed": False,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "no_coinbase_submit": True,
        "coinbase_call_attempted": False,
        "live_submission_attempted": False,
        "live_order_submitted": False,
        "cancel_submitted": False,
        "replace_submitted": False,
        "new_exit_order_created": False,
        "blockers": [],
        "warnings": [],
        "safety_policy": {
            "preview_only_default": True,
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_replace": True,
            "does_not_mutate_orders": True,
            "does_not_call_coinbase": True,
            "requires_ack_for_apply": True,
            "replication_isolation_required": True,
        },
        "source_evidence": {
            "recovery_preview_values_source": RECOVERY_VALUES_SOURCE,
            "local_order_status": str((local_order or {}).get("status") or ""),
            "local_order_remaining_size": str((local_order or {}).get("remaining_size") or ""),
            "local_order_linked_position_id": str((local_order or {}).get("linked_position_id") or ""),
            "local_position_status": str(position.get("status") or ""),
            "local_position_size_base": str(position.get("position_size_base") or "0"),
            "local_bot_managed_base": str(position.get("bot_managed_base") or "0"),
            "open_d3_orders_count_same_position": len(open_d3_orders),
        },
        "proposed_position_updates": {},
        "proposed_position_changes": {},
        "invariants": {},
    }

    def block(reason: str) -> None:
        report["blockers"].append(reason)

    order_status = str((local_order or {}).get("status") or "").strip().lower()
    order_remaining_size = _to_decimal((local_order or {}).get("remaining_size") or (local_order or {}).get("size_base"), "0")
    order_filled_base = _to_decimal((local_order or {}).get("filled_base") or (local_order or {}).get("filled_size_base"), "0")
    order_fill_count = int((local_order or {}).get("fill_count") or 0)

    math_matches = managed_base == (position_base + reserved_base)
    negative_values = position_base < ZERO or reserved_base < ZERO or managed_base < ZERO
    position_already_open = str(position.get("status") or "").strip().lower() == "open"
    current_position_base = _to_decimal(position.get("position_size_base"), "0")
    current_bot_managed_base = _to_decimal(position.get("bot_managed_base"), "0")
    current_reserved_base = _to_decimal(position.get("reserved_base_open_exit_orders"), "0")
    existing_coherent_open = (
        position_already_open
        and current_position_base == position_base
        and current_bot_managed_base == managed_base
        and current_reserved_base == reserved_base
    )

    report["invariants"] = {
        "open_d3_order_found": isinstance(local_order, dict),
        "single_matching_open_d3_order": len(open_d3_orders) == 1,
        "client_order_id_matches": bool(local_order) and str(local_order.get("client_order_id") or "").strip() == selected_client,
        "exchange_order_id_matches": bool(local_order) and str(local_order.get("exchange_order_id") or local_order.get("order_id") or "").strip() == selected_exchange,
        "linked_position_id_matches": bool(local_order) and str(local_order.get("linked_position_id") or "").strip() == selected_linked,
        "local_order_open_submitted": order_status in SAFE_OPEN_ORDER_STATUSES,
        "remaining_size_matches_reserved_base": order_remaining_size == reserved_base,
        "filled_base_zero": order_filled_base == ZERO,
        "fill_count_zero": order_fill_count == 0,
        "proposed_base_math_matches": math_matches,
        "proposed_nonnegative": not negative_values,
        "position_not_already_open_and_coherent": not existing_coherent_open,
        "replication_disabled": not _env_flag_enabled("REPLICATION_ENABLED", False),
        "live_exit_orders_disabled": not _env_flag_enabled("ENABLE_LIVE_EXIT_ORDERS", False),
        "autonomous_exits_disabled": not _env_flag_enabled("AUTONOMOUS_ALLOW_EXITS", False),
        "d3_actual_submit_disabled": not _env_flag_enabled("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", False),
        "phase_c_exit_limit_orders_disabled": _env_flag_enabled("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", True),
    }

    if not isinstance(local_order, dict):
        block("recovery_open_d3_order_missing")
    if len(open_d3_orders) != 1:
        block("recovery_second_or_missing_open_d3_exit_order")
    if local_order and str(local_order.get("client_order_id") or "").strip() != selected_client:
        block("recovery_client_order_id_mismatch")
    if local_order and str(local_order.get("exchange_order_id") or local_order.get("order_id") or "").strip() != selected_exchange:
        block("recovery_exchange_order_id_mismatch")
    if local_order and str(local_order.get("linked_position_id") or "").strip() != selected_linked:
        block("recovery_linked_position_id_mismatch")
    if local_order and order_status not in SAFE_OPEN_ORDER_STATUSES:
        block("recovery_d3_order_not_submitted_or_open")
    if local_order and order_remaining_size != reserved_base:
        block("recovery_remaining_size_reserved_base_mismatch")
    if local_order and (order_filled_base > ZERO or order_fill_count > 0):
        block("recovery_filled_evidence_present")
    if not math_matches:
        block("recovery_proposed_base_math_incoherent")
    if negative_values:
        block("recovery_negative_base_not_allowed")
    if existing_coherent_open:
        block("recovery_position_already_open_and_coherent")
    if _env_flag_enabled("REPLICATION_ENABLED", False):
        block("recovery_replication_enabled_forbidden")
    if _env_flag_enabled("ENABLE_LIVE_EXIT_ORDERS", False):
        block("recovery_live_exit_orders_enabled_forbidden")
    if _env_flag_enabled("AUTONOMOUS_ALLOW_EXITS", False):
        block("recovery_autonomous_exits_enabled_forbidden")
    if _env_flag_enabled("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", False):
        block("recovery_d3_actual_submit_enabled_forbidden")
    if not _env_flag_enabled("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", True):
        block("recovery_phase_c_exit_limit_orders_not_disabled")

    updates = _build_recovery_updates(
        position,
        position_size_base=position_base,
        reserved_base_open_exit_orders=reserved_base,
        bot_managed_base=managed_base,
        client_order_id=selected_client,
        exchange_order_id=selected_exchange,
        linked_position_id=selected_linked,
    )
    updates["recovery_preview_only"] = not bool(apply)

    report["proposed_position_updates"] = updates
    report["proposed_position_changes"] = _compute_changes(position, updates)

    if report["blockers"]:
        report["status"] = "d3_local_position_recovery_blocked"
        report["suggested_action"] = "no_apply"
    elif apply:
        if not report["recovery_ack_valid"]:
            report["blockers"].append("recovery_apply_ack_required")
            report["status"] = "d3_local_position_recovery_blocked"
            report["suggested_action"] = "ack_required"
        else:
            updated = positions.upsert_position(selected_ticker, updates)
            report["status"] = "d3_local_position_recovery_applied"
            report["suggested_action"] = "applied"
            report["state_write_performed"] = True
            report["no_state_write"] = False
            report["applied_position"] = updated
    else:
        report["status"] = "d3_local_position_recovery_preview_ready"
        report["suggested_action"] = "preview_only"

    report["blockers"] = sorted(set(report["blockers"]))
    return _json_safe(report)


__all__ = [
    "PHASE_D3_LOCAL_POSITION_RECOVERY_ACK",
    "PHASE_D3_LOCAL_POSITION_RECOVERY_PHASE",
    "RECOVERY_REASON",
    "RECOVERY_SOURCE",
    "RECOVERY_VALUES_SOURCE",
    "build_phase_d3_local_position_recovery_report",
]
