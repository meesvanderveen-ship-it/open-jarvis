from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.atomic_io import process_lock, runtime_mutation_lock_path
from bot.coinbase_order_snapshot import (
    fetch_coinbase_order_snapshot_with_diagnostics,
    normalize_order_status,
)
from bot.order_lifecycle import is_open_order_status
from bot.order_store import FINAL_ORDER_STATUSES, OPEN_ORDER_STATUSES, OrderStore
from bot.phase_d3_open_exit_position_guard import (
    find_open_d3_exit_reservations_for_position,
    logical_position_id_candidates as guard_logical_position_id_candidates,
    match_open_d3_exit_order_to_position,
)
from bot.phase_d3_live_exit_reconciliation import (
    D3_LIVE_EXIT_RECONCILE_ACK,
    reconcile_phase_d3_live_exit_order,
)
from bot.state_store import StateStore


D3_OPEN_EXIT_LIFECYCLE_PHASE = "D3_open_exit_lifecycle_manager_v1"
D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK = (
    "I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_LIFECYCLE_APPLY"
)
ZERO = Decimal("0")
# Compatibility export for D3 callers. The canonical predicate below is used
# for the actual lifecycle scan so new exchange-open aliases fail closed.
D3_SAFE_OPEN_ORDER_STATUSES = OPEN_ORDER_STATUSES


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _env_flag_enabled(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def _d3_lifecycle_mutation_lock_path(order_store: Optional[OrderStore]) -> str:
    return str(runtime_mutation_lock_path(order_store=order_store))


def logical_position_id_candidates(
    position: Optional[Dict[str, Any]] = None,
    *,
    linked_position_id: str = "",
) -> List[str]:
    return guard_logical_position_id_candidates(position, linked_position_id=linked_position_id)


def order_matches_logical_position(
    order: Dict[str, Any],
    *,
    position: Optional[Dict[str, Any]] = None,
    linked_position_id: str = "",
) -> bool:
    return bool(
        match_open_d3_exit_order_to_position(
            order,
            ticker=_normalize_ticker(order.get("ticker")),
            position=position,
            linked_position_id=linked_position_id,
            order_store=OrderStore(),
        ).get("matched")
    )


def iter_matching_open_d3_orders(
    order_store: Optional[OrderStore] = None,
    *,
    ticker: str,
    position: Optional[Dict[str, Any]] = None,
    linked_position_id: str = "",
) -> List[Dict[str, Any]]:
    return find_open_d3_exit_reservations_for_position(
        ticker=ticker,
        position=position,
        linked_position_id=linked_position_id,
        order_store=order_store or OrderStore(),
    )


def scan_open_d3_exit_lifecycle_orders(
    order_store: Optional[OrderStore] = None,
    *,
    ticker: str = "",
) -> List[Dict[str, Any]]:
    store = order_store or OrderStore()
    selected_ticker = _normalize_ticker(ticker)
    orders: List[Dict[str, Any]] = []
    for order in store.all_orders():
        if selected_ticker and _normalize_ticker(order.get("ticker") or order.get("product_id")) != selected_ticker:
            continue
        if str(order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
            continue
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if not is_open_order_status(order.get("status")):
            continue
        orders.append(dict(order))
    return orders


def reserved_base_for_matching_open_d3_orders(
    order_store: Optional[OrderStore] = None,
    *,
    ticker: str,
    position: Optional[Dict[str, Any]] = None,
    linked_position_id: str = "",
    ignore_client_order_id: str = "",
) -> Decimal:
    ignored = str(ignore_client_order_id or "").strip()
    total = ZERO
    for order in iter_matching_open_d3_orders(
        order_store,
        ticker=ticker,
        position=position,
        linked_position_id=linked_position_id,
    ):
        if ignored and str(order.get("client_order_id") or "").strip() == ignored:
            continue
        total += max(
            ZERO,
            _to_decimal(order.get("remaining_size") or order.get("size_base"), "0"),
        )
    return total


def _position_base(position: Dict[str, Any]) -> Decimal:
    for key in ("position_size_base", "bot_managed_base", "base_size", "filled_size_base"):
        value = _to_decimal(position.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _bot_managed_base(position: Dict[str, Any]) -> Decimal:
    for key in ("bot_managed_base", "position_size_base", "base_size", "filled_size_base"):
        value = _to_decimal(position.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _find_local_d3_order(
    store: OrderStore,
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    position: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    selected_client = str(client_order_id or "").strip()
    selected_exchange = str(exchange_order_id or "").strip()
    selected_linked = str(linked_position_id or "").strip()
    if selected_client:
        order = store.get_order(selected_client)
        if isinstance(order, dict):
            return dict(order)
    for order in store.all_orders():
        if selected_ticker and _normalize_ticker(order.get("ticker")) != selected_ticker:
            continue
        exchange_id = str(order.get("exchange_order_id") or order.get("order_id") or "").strip()
        if selected_exchange and exchange_id == selected_exchange:
            return dict(order)
        if selected_linked and order_matches_logical_position(
            order,
            position=position,
            linked_position_id=selected_linked,
        ):
            if str(order.get("phase") or "").strip() == "D3_controlled_live_reduce_only_exits":
                return dict(order)
    return None


def _safety_blockers() -> List[str]:
    blockers: List[str] = []
    if _env_flag_enabled("REPLICATION_ENABLED", False):
        blockers.append("replication_enabled_blocks_d3_open_exit_lifecycle_apply")
    if _env_flag_enabled("ENABLE_LIVE_EXIT_ORDERS", False):
        blockers.append("enable_live_exit_orders_must_remain_false_for_local_lifecycle_apply")
    if _env_flag_enabled("AUTONOMOUS_ALLOW_EXITS", False):
        blockers.append("autonomous_allow_exits_must_remain_false_for_local_lifecycle_apply")
    if _env_flag_enabled("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", False):
        blockers.append("phase_d3_actual_submit_must_remain_false_for_local_lifecycle_apply")
    if not _env_flag_enabled("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", True):
        blockers.append("phase_c_disable_exit_limit_orders_must_remain_true_for_local_lifecycle_apply")
    return blockers


def _normalize_snapshot_from_fixture(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    raw = _as_dict(snapshot)
    normalized = str(raw.get("normalized_status") or "").strip().lower()
    raw_status = str(raw.get("raw_status") or "").strip().upper()
    filled_base = str(raw.get("filled_base") or "0")
    if not normalized:
        normalized = normalize_order_status(raw_status, filled_base=filled_base)
    return {
        "coinbase_call_attempted": bool(raw.get("coinbase_call_attempted", False)),
        "coinbase_call_succeeded": bool(raw.get("coinbase_call_succeeded", False)),
        "coinbase_snapshot_unavailable": bool(raw.get("coinbase_snapshot_unavailable", False)),
        "coinbase_error_type": str(raw.get("coinbase_error_type") or ""),
        "coinbase_error_message": str(raw.get("coinbase_error_message") or ""),
        "coinbase_error_stage": str(raw.get("coinbase_error_stage") or ""),
        "coinbase_order_lookup_method_attempted": list(raw.get("coinbase_order_lookup_method_attempted") or []),
        "coinbase_order_lookup_succeeded_method": str(raw.get("coinbase_order_lookup_succeeded_method") or ""),
        "coinbase_order_lookup_failed_methods": list(raw.get("coinbase_order_lookup_failed_methods") or []),
        "order_id_used": str(raw.get("order_id_used") or ""),
        "client_order_id_used": str(raw.get("client_order_id_used") or ""),
        "product_id_used": str(raw.get("product_id_used") or ""),
        "include_fills": bool(raw.get("include_fills", False)),
        "raw_response_shape": _as_dict(raw.get("raw_response_shape")),
        "raw_status": raw_status,
        "normalized_status": normalized,
        "filled_base": filled_base,
        "filled_quote": str(raw.get("filled_quote") or "0"),
        "avg_fill_price": str(raw.get("avg_fill_price") or "0"),
        "fill_count": int(raw.get("fill_count") or 0),
        "remaining_size": str(raw.get("remaining_size") or "0"),
        "fees": str(raw.get("fees") or "0"),
        "commission": str(raw.get("commission") or raw.get("fees") or "0"),
        "evidence_source": str(raw.get("evidence_source") or "snapshot_fixture_or_preloaded"),
        "evidence_timestamp": str(raw.get("evidence_timestamp") or raw.get("snapshot_timestamp") or _now_iso()),
        "snapshot": raw.get("snapshot") or raw,
        "warnings": list(raw.get("warnings") or []),
        "blockers": list(raw.get("blockers") or []),
    }


def _evidence_hash(snapshot: Dict[str, Any]) -> str:
    payload = {
        "normalized_status": str(snapshot.get("normalized_status") or ""),
        "raw_status": str(snapshot.get("raw_status") or ""),
        "filled_base": str(snapshot.get("filled_base") or "0"),
        "filled_quote": str(snapshot.get("filled_quote") or "0"),
        "avg_fill_price": str(snapshot.get("avg_fill_price") or "0"),
        "fill_count": int(snapshot.get("fill_count") or 0),
        "remaining_size": str(snapshot.get("remaining_size") or "0"),
        "fees": str(snapshot.get("fees") or "0"),
    }
    text = repr(sorted(payload.items())).encode("utf-8")
    return hashlib.sha256(text).hexdigest()


def _build_lifecycle_metadata(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "last_d3_exit_lifecycle_apply_at": _now_iso(),
        "last_d3_exit_lifecycle_evidence_hash": _evidence_hash(snapshot),
        "last_d3_exit_lifecycle_applied_status": str(snapshot.get("normalized_status") or ""),
        "last_d3_exit_lifecycle_applied_filled_base": str(snapshot.get("filled_base") or "0"),
        "last_d3_exit_lifecycle_applied_remaining_size": str(snapshot.get("remaining_size") or "0"),
    }


def _already_applied_same_evidence(local_order: Dict[str, Any], snapshot: Dict[str, Any]) -> bool:
    return (
        str(local_order.get("last_d3_exit_lifecycle_evidence_hash") or "").strip()
        and str(local_order.get("last_d3_exit_lifecycle_evidence_hash") or "").strip() == _evidence_hash(snapshot)
        and str(local_order.get("last_d3_exit_lifecycle_applied_status") or "").strip()
        == str(snapshot.get("normalized_status") or "").strip()
        and str(local_order.get("last_d3_exit_lifecycle_applied_filled_base") or "0").strip()
        == str(snapshot.get("filled_base") or "0").strip()
        and str(local_order.get("last_d3_exit_lifecycle_applied_remaining_size") or "0").strip()
        == str(snapshot.get("remaining_size") or "0").strip()
    )


def _build_keep_open_preview_report(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    local_order: Dict[str, Any],
    position: Dict[str, Any],
    reservation_before: Decimal,
    duplicate_exit_detected: bool,
    oversell_detected: bool,
    apply_local: bool,
) -> Dict[str, Any]:
    local_status = str(local_order.get("status") or "").strip().lower()
    local_position_status = str(position.get("status") or "").strip().lower()
    mode = "applied" if apply_local else "preview"
    status = (
        "d3_open_exit_lifecycle_applied_noop"
        if apply_local
        else "d3_open_exit_lifecycle_preview_ready"
    )
    proposed_action = "keep_open" if apply_local else "keep_local_open_no_live_snapshot"
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D3_OPEN_EXIT_LIFECYCLE_PHASE,
        "status": status,
        "mode": mode,
        "ticker": ticker,
        "client_order_id": client_order_id,
        "exchange_order_id": exchange_order_id,
        "linked_position_id": linked_position_id,
        "coinbase_call_attempted": False,
        "coinbase_call_succeeded": False,
        "coinbase_snapshot_unavailable": False,
        "coinbase_error_type": "",
        "coinbase_error_message": "",
        "coinbase_error_stage": "",
        "coinbase_order_lookup_method_attempted": [],
        "coinbase_order_lookup_succeeded_method": "",
        "coinbase_order_lookup_failed_methods": [],
        "order_id_used": "",
        "client_order_id_used": "",
        "product_id_used": "",
        "include_fills": False,
        "raw_response_shape": {},
        "coinbase_raw_status": "",
        "normalized_status": "local_only_open",
        "fill_count": int(local_order.get("fill_count") or 0),
        "filled_base": str(local_order.get("filled_base") or local_order.get("filled_size") or "0"),
        "filled_quote": str(local_order.get("filled_quote") or local_order.get("filled_quote_value") or "0"),
        "fees": str(local_order.get("fees_paid") or local_order.get("fees") or "0"),
        "avg_fill_price": str(local_order.get("avg_fill_price") or "0"),
        "remaining_size": str(local_order.get("remaining_size") or local_order.get("size_base") or "0"),
        "local_order_status_before": local_status,
        "local_order_status_after_preview": local_status,
        "local_position_status_before": local_position_status,
        "local_position_status_after_preview": local_position_status or "open",
        "proposed_action": proposed_action,
        "applied_actions": [],
        "state_write_performed": False,
        "no_state_write": True,
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "duplicate_exit_detected": duplicate_exit_detected,
        "oversell_detected": oversell_detected,
        "reservation_before": str(reservation_before),
        "reservation_after_preview": str(reservation_before),
        "blockers": [],
        "warnings": [],
        "proposed_order_updates": {},
        "proposed_position_updates": {},
        "source_evidence": {
            "local_only_preview": True,
            "local_order_status": local_status,
            "local_position_status": local_position_status,
        },
        "evidence_source": "local_state_only",
        "evidence_timestamp": "",
        "evidence_hash": "",
    })


def _build_phase_d3_open_exit_lifecycle_report_unlocked(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    snapshot: Optional[Dict[str, Any]] = None,
    allow_coinbase_poll: bool = False,
    apply_local: bool = False,
    apply_ack: str = "",
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    selected_client = str(client_order_id or "").strip()
    selected_exchange = str(exchange_order_id or "").strip()
    selected_linked = str(linked_position_id or "").strip()
    store = order_store or OrderStore()
    positions = state_store or StateStore()
    position = positions.get_position(selected_ticker) or {}
    local_order = _find_local_d3_order(
        store,
        ticker=selected_ticker,
        client_order_id=selected_client,
        exchange_order_id=selected_exchange,
        linked_position_id=selected_linked,
        position=position,
    )

    report: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "phase": D3_OPEN_EXIT_LIFECYCLE_PHASE,
        "status": "blocked_review_required",
        "mode": "applied" if apply_local else "preview",
        "ticker": selected_ticker,
        "client_order_id": selected_client,
        "exchange_order_id": selected_exchange,
        "linked_position_id": selected_linked,
        "coinbase_call_attempted": False,
        "coinbase_call_succeeded": False,
        "coinbase_snapshot_unavailable": False,
        "coinbase_error_type": "",
        "coinbase_error_message": "",
        "coinbase_error_stage": "",
        "coinbase_order_lookup_method_attempted": [],
        "coinbase_order_lookup_succeeded_method": "",
        "coinbase_order_lookup_failed_methods": [],
        "order_id_used": "",
        "client_order_id_used": "",
        "product_id_used": "",
        "include_fills": False,
        "raw_response_shape": {},
        "coinbase_raw_status": "",
        "normalized_status": "",
        "fill_count": 0,
        "filled_base": "0",
        "filled_quote": "0",
        "fees": "0",
        "avg_fill_price": "0",
        "remaining_size": "0",
        "local_order_status_before": "",
        "local_order_status_after_preview": "",
        "local_position_status_before": str(position.get("status") or "").strip().lower(),
        "local_position_status_after_preview": str(position.get("status") or "").strip().lower(),
        "proposed_action": "review_required",
        "applied_actions": [],
        "state_write_performed": False,
        "no_state_write": True,
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "duplicate_exit_detected": False,
        "oversell_detected": False,
        "reservation_before": "0",
        "reservation_after_preview": "0",
        "blockers": [],
        "warnings": [],
        "required_apply_ack": D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
        "apply_requested": bool(apply_local),
        "apply_ack_valid": not apply_local or str(apply_ack or "").strip() == D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
        "source_evidence": {},
        "proposed_order_updates": {},
        "proposed_position_updates": {},
        "evidence_source": "",
        "evidence_timestamp": "",
        "evidence_hash": "",
    }

    if not isinstance(local_order, dict):
        report["blockers"].append("matching_open_d3_order_not_found")
        return _json_safe(report)

    matching_orders = iter_matching_open_d3_orders(
        store,
        ticker=selected_ticker,
        position=position,
        linked_position_id=selected_linked or str(local_order.get("linked_position_id") or ""),
    )
    if len(matching_orders) > 1:
        report["blockers"].append("duplicate_open_d3_exit_order_for_position")
    report["duplicate_exit_detected"] = len(matching_orders) > 1

    local_status = str(local_order.get("status") or "").strip().lower()
    report["local_order_status_before"] = local_status
    report["local_order_status_after_preview"] = local_status
    report["remaining_size"] = str(local_order.get("remaining_size") or local_order.get("size_base") or "0")
    report["filled_base"] = str(local_order.get("filled_base") or local_order.get("filled_size") or "0")
    report["filled_quote"] = str(local_order.get("filled_quote") or local_order.get("filled_quote_value") or "0")
    report["fees"] = str(local_order.get("fees_paid") or local_order.get("fees") or "0")
    report["fill_count"] = int(local_order.get("fill_count") or 0)
    report["avg_fill_price"] = str(local_order.get("avg_fill_price") or "0")
    report["source_evidence"]["local_order"] = {
        "status": local_status,
        "linked_position_id": str(local_order.get("linked_position_id") or ""),
    }

    if selected_client and str(local_order.get("client_order_id") or "").strip() != selected_client:
        report["blockers"].append("client_order_id_mismatch")
    if selected_exchange and str(local_order.get("exchange_order_id") or local_order.get("order_id") or "").strip() != selected_exchange:
        report["blockers"].append("exchange_order_id_mismatch")
    if not str(local_order.get("exchange_order_id") or local_order.get("order_id") or selected_exchange or "").strip():
        report["blockers"].append("exchange_order_id_required_for_d3_lifecycle")
    if selected_linked and str(local_order.get("linked_position_id") or "").strip() != selected_linked:
        report["blockers"].append("linked_position_id_mismatch")
    if str(local_order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
        report["blockers"].append("matching_order_not_d3_exit")

    reservation_before = reserved_base_for_matching_open_d3_orders(
        store,
        ticker=selected_ticker,
        position=position,
        linked_position_id=selected_linked or str(local_order.get("linked_position_id") or ""),
    )
    report["reservation_before"] = str(reservation_before)
    report["reservation_after_preview"] = str(reservation_before)

    total_manageable = _bot_managed_base(position)
    available_base = _position_base(position)
    report["oversell_detected"] = reservation_before > max(total_manageable, available_base) and max(total_manageable, available_base) > ZERO
    if report["oversell_detected"]:
        report["blockers"].append("open_d3_exit_reservation_exceeds_manageable_base")

    report["source_evidence"]["logical_position_ids"] = logical_position_id_candidates(
        position,
        linked_position_id=selected_linked,
    )

    if apply_local and not report["apply_ack_valid"]:
        report["blockers"].append("d3_open_exit_lifecycle_apply_ack_required")
        return _json_safe(report)
    if apply_local:
        report["blockers"].extend(_safety_blockers())

    if report["blockers"]:
        return _json_safe(report)

    if snapshot is None and allow_coinbase_poll:
        report["coinbase_call_attempted"] = True
        if coinbase_client is None:
            report["status"] = "blocked_review_required"
            report["blockers"].append("coinbase_client_missing")
            return _json_safe(report)
        try:
            normalized = fetch_coinbase_order_snapshot_with_diagnostics(
                coinbase_client=coinbase_client,
                order_id=selected_exchange,
                local_order=local_order,
                include_fills=True,
            )
        except Exception as exc:
            report["status"] = "blocked_review_required"
            report["blockers"].append("coinbase_snapshot_unavailable")
            report["warnings"].append(f"coinbase_poll_failed:{type(exc).__name__}")
            report["coinbase_call_succeeded"] = False
            report["coinbase_snapshot_unavailable"] = True
            report["coinbase_error_type"] = type(exc).__name__
            report["coinbase_error_message"] = str(exc)
            report["coinbase_error_stage"] = "fetch_coinbase_order_snapshot_with_diagnostics"
            report["order_id_used"] = selected_exchange
            report["client_order_id_used"] = selected_client
            report["product_id_used"] = selected_ticker
            report["include_fills"] = True
            return _json_safe(report)
        report["coinbase_call_succeeded"] = bool(normalized.get("coinbase_call_succeeded", True))
        report["coinbase_snapshot_unavailable"] = bool(normalized.get("coinbase_snapshot_unavailable", False))
        report["coinbase_error_type"] = str(normalized.get("coinbase_error_type") or "")
        report["coinbase_error_message"] = str(normalized.get("coinbase_error_message") or "")
        report["coinbase_error_stage"] = str(normalized.get("coinbase_error_stage") or "")
        report["coinbase_order_lookup_method_attempted"] = list(normalized.get("coinbase_order_lookup_method_attempted") or [])
        report["coinbase_order_lookup_succeeded_method"] = str(normalized.get("coinbase_order_lookup_succeeded_method") or "")
        report["coinbase_order_lookup_failed_methods"] = list(normalized.get("coinbase_order_lookup_failed_methods") or [])
        report["order_id_used"] = str(normalized.get("order_id_used") or selected_exchange)
        report["client_order_id_used"] = str(normalized.get("client_order_id_used") or selected_client)
        report["product_id_used"] = str(normalized.get("product_id_used") or selected_ticker)
        report["include_fills"] = bool(normalized.get("include_fills", True))
        report["raw_response_shape"] = _as_dict(normalized.get("raw_response_shape"))
        if normalized.get("coinbase_snapshot_unavailable"):
            report["status"] = "blocked_review_required"
            report["blockers"] = list(dict.fromkeys(report["blockers"] + list(normalized.get("blockers") or ["coinbase_snapshot_unavailable"])))
            report["warnings"] = list(dict.fromkeys(report["warnings"] + list(normalized.get("warnings") or [])))
            return _json_safe(report)
        snapshot = {
            "coinbase_call_attempted": True,
            "coinbase_call_succeeded": bool(normalized.get("coinbase_call_succeeded", True)),
            "raw_status": normalized.get("raw_status") or normalized.get("status") or "",
            "normalized_status": normalized.get("normalized_status") or "",
            "filled_base": normalized.get("filled_base") or "0",
            "filled_quote": normalized.get("filled_quote") or "0",
            "avg_fill_price": normalized.get("avg_fill_price") or "0",
            "fill_count": int((normalized.get("fills_summary") or {}).get("fill_count") or 0),
            "remaining_size": normalized.get("remaining_size") or local_order.get("remaining_size") or "0",
            "fees": str(local_order.get("fees_paid") or local_order.get("fees") or "0"),
            "commission": str(local_order.get("fees_paid") or local_order.get("fees") or "0"),
            "evidence_source": str(normalized.get("evidence_source") or "coinbase_order_snapshot"),
            "evidence_timestamp": _now_iso(),
            "snapshot": normalized,
            "coinbase_snapshot_unavailable": bool(normalized.get("coinbase_snapshot_unavailable", False)),
            "coinbase_error_type": str(normalized.get("coinbase_error_type") or ""),
            "coinbase_error_message": str(normalized.get("coinbase_error_message") or ""),
            "coinbase_error_stage": str(normalized.get("coinbase_error_stage") or ""),
            "coinbase_order_lookup_method_attempted": list(normalized.get("coinbase_order_lookup_method_attempted") or []),
            "coinbase_order_lookup_succeeded_method": str(normalized.get("coinbase_order_lookup_succeeded_method") or ""),
            "coinbase_order_lookup_failed_methods": list(normalized.get("coinbase_order_lookup_failed_methods") or []),
            "order_id_used": str(normalized.get("order_id_used") or selected_exchange),
            "client_order_id_used": str(normalized.get("client_order_id_used") or selected_client),
            "product_id_used": str(normalized.get("product_id_used") or selected_ticker),
            "include_fills": bool(normalized.get("include_fills", True)),
            "raw_response_shape": _as_dict(normalized.get("raw_response_shape")),
            "warnings": list(normalized.get("warnings") or []),
            "blockers": list(normalized.get("blockers") or []),
        }

    if snapshot is None:
        if apply_local:
            report["status"] = "blocked_review_required"
            report["blockers"].append("coinbase_evidence_required_for_apply")
            return _json_safe(report)
        return _build_keep_open_preview_report(
            ticker=selected_ticker,
            client_order_id=selected_client,
            exchange_order_id=selected_exchange,
            linked_position_id=selected_linked,
            local_order=local_order,
            position=position,
            reservation_before=reservation_before,
            duplicate_exit_detected=report["duplicate_exit_detected"],
            oversell_detected=report["oversell_detected"],
            apply_local=apply_local,
        )

    normalized_snapshot = _normalize_snapshot_from_fixture(snapshot)
    report["coinbase_call_attempted"] = bool(normalized_snapshot.get("coinbase_call_attempted"))
    report["coinbase_call_succeeded"] = bool(normalized_snapshot.get("coinbase_call_succeeded", True))
    report["coinbase_snapshot_unavailable"] = bool(normalized_snapshot.get("coinbase_snapshot_unavailable", False))
    report["coinbase_error_type"] = str(normalized_snapshot.get("coinbase_error_type") or "")
    report["coinbase_error_message"] = str(normalized_snapshot.get("coinbase_error_message") or "")
    report["coinbase_error_stage"] = str(normalized_snapshot.get("coinbase_error_stage") or "")
    report["coinbase_order_lookup_method_attempted"] = list(normalized_snapshot.get("coinbase_order_lookup_method_attempted") or [])
    report["coinbase_order_lookup_succeeded_method"] = str(normalized_snapshot.get("coinbase_order_lookup_succeeded_method") or "")
    report["coinbase_order_lookup_failed_methods"] = list(normalized_snapshot.get("coinbase_order_lookup_failed_methods") or [])
    report["order_id_used"] = str(normalized_snapshot.get("order_id_used") or report["exchange_order_id"] or "")
    report["client_order_id_used"] = str(normalized_snapshot.get("client_order_id_used") or report["client_order_id"] or "")
    report["product_id_used"] = str(normalized_snapshot.get("product_id_used") or report["ticker"] or "")
    report["include_fills"] = bool(normalized_snapshot.get("include_fills", report["coinbase_call_attempted"]))
    report["raw_response_shape"] = _as_dict(normalized_snapshot.get("raw_response_shape"))
    report["coinbase_raw_status"] = str(normalized_snapshot.get("raw_status") or "")
    report["normalized_status"] = str(normalized_snapshot.get("normalized_status") or "")
    report["fill_count"] = int(normalized_snapshot.get("fill_count") or 0)
    report["filled_base"] = str(normalized_snapshot.get("filled_base") or "0")
    report["filled_quote"] = str(normalized_snapshot.get("filled_quote") or "0")
    report["fees"] = str(normalized_snapshot.get("fees") or normalized_snapshot.get("commission") or "0")
    report["avg_fill_price"] = str(normalized_snapshot.get("avg_fill_price") or "0")
    report["remaining_size"] = str(normalized_snapshot.get("remaining_size") or report["remaining_size"] or "0")
    report["evidence_source"] = str(normalized_snapshot.get("evidence_source") or "")
    report["evidence_timestamp"] = str(normalized_snapshot.get("evidence_timestamp") or "")
    report["evidence_hash"] = _evidence_hash(normalized_snapshot)
    report["warnings"] = list(dict.fromkeys(report["warnings"] + list(normalized_snapshot.get("warnings") or [])))

    if not normalized_snapshot.get("coinbase_call_succeeded", True):
        report["status"] = "blocked_review_required"
        report["blockers"].append("coinbase_snapshot_unavailable")
        return _json_safe(report)

    if normalized_snapshot.get("blockers"):
        report["status"] = "blocked_review_required"
        report["blockers"] = list(dict.fromkeys(report["blockers"] + list(normalized_snapshot.get("blockers") or [])))
        return _json_safe(report)

    normalized_status = str(normalized_snapshot.get("normalized_status") or "").strip().lower()
    report["normalized_status"] = normalized_status
    if normalized_status not in {
        "open",
        "partially_filled",
        "filled",
        "cancelled",
        "expired",
        "rejected",
    }:
        report["status"] = "blocked_review_required"
        report["blockers"].append("unknown_coinbase_order_status")
        return _json_safe(report)

    if normalized_status in {"partially_filled", "filled"}:
        if not (
            _to_decimal(normalized_snapshot.get("filled_base"), "0") > ZERO
            or int(normalized_snapshot.get("fill_count") or 0) > 0
        ):
            report["status"] = "blocked_review_required"
            report["blockers"].append("fill_evidence_required_for_partial_or_filled_apply")
            return _json_safe(report)

    if normalized_status in {"cancelled", "expired", "rejected"}:
        if (
            _to_decimal(normalized_snapshot.get("filled_base"), "0") > ZERO
            or int(normalized_snapshot.get("fill_count") or 0) > 0
        ):
            report["status"] = "blocked_review_required"
            report["blockers"].append("terminal_non_fill_status_contains_fill_evidence")
            return _json_safe(report)

    if apply_local and _already_applied_same_evidence(local_order, normalized_snapshot):
        report["status"] = "d3_open_exit_lifecycle_apply_idempotent_noop"
        report["proposed_action"] = "already_applied_noop"
        report["applied_actions"] = []
        report["state_write_performed"] = False
        report["no_state_write"] = True
        report["warnings"].append("same_evidence_already_applied_noop")
        return _json_safe(report)

    if normalized_status == "open":
        if report["coinbase_call_attempted"] and not int(normalized_snapshot.get("fill_count") or 0):
            report["proposed_action"] = (
                "keep_open_status_only_evidence"
                if "status_only" in str(report.get("evidence_source") or "")
                else "keep_open"
            )
        else:
            report["proposed_action"] = "keep_open"
        report["status"] = (
            "d3_open_exit_lifecycle_applied_noop"
            if apply_local
            else "d3_open_exit_lifecycle_keep_open_preview"
        )
        return _json_safe(report)

    reconcile_report = reconcile_phase_d3_live_exit_order(
        ticker=selected_ticker,
        client_order_id=selected_client,
        exchange_order_id=selected_exchange,
        linked_position_id=selected_linked,
        snapshot=normalized_snapshot,
        order_store=store,
        state_store=positions,
        apply=apply_local,
        apply_ack=D3_LIVE_EXIT_RECONCILE_ACK if apply_local else "",
    )
    reconcile_applied = str(reconcile_report.get("status") or "").endswith("_applied")
    preview_reservation_after = report["reservation_after_preview"]
    if str((_as_dict(reconcile_report.get("proposed_order_updates")) or {}).get("status") or "").strip().lower() in FINAL_ORDER_STATUSES:
        preview_reservation_after = "0"
    elif "last_d3_reconcile_reserved_base_this_exit_after_fill" in _as_dict(reconcile_report.get("proposed_position_updates")):
        preview_reservation_after = str(
            _as_dict(reconcile_report.get("proposed_position_updates")).get(
                "last_d3_reconcile_reserved_base_this_exit_after_fill",
                preview_reservation_after,
            )
        )

    report.update({
        "status": (
            "d3_open_exit_lifecycle_applied"
            if apply_local and not reconcile_report.get("blockers")
            else "d3_open_exit_lifecycle_reconcile_preview_ready"
        ),
        "proposed_action": str(reconcile_report.get("suggested_action") or "review_required"),
        "applied_actions": [
            str(reconcile_report.get("suggested_action") or "")
        ] if apply_local and not reconcile_report.get("blockers") else [],
        "state_write_performed": bool(reconcile_report.get("state_write_performed") or reconcile_applied),
        "no_state_write": not bool(reconcile_report.get("state_write_performed") or reconcile_applied),
        "blockers": list(reconcile_report.get("blockers") or []),
        "warnings": list(reconcile_report.get("warnings") or []),
        "proposed_order_updates": _as_dict(reconcile_report.get("proposed_order_updates")),
        "proposed_position_updates": _as_dict(reconcile_report.get("proposed_position_updates")),
        "local_order_status_after_preview": str(
            (_as_dict(reconcile_report.get("proposed_order_updates")) or {}).get("status")
            or local_status
        ).strip().lower(),
        "local_position_status_after_preview": str(
            (_as_dict(reconcile_report.get("proposed_position_updates")) or {}).get("status")
            or report["local_position_status_before"]
        ).strip().lower(),
        "reservation_after_preview": preview_reservation_after,
        "source_evidence": {
            **report["source_evidence"],
            "reconcile_report_status": str(reconcile_report.get("status") or ""),
            "snapshot_status": normalized_status,
        },
    })
    if apply_local and not report["blockers"] and report["state_write_performed"]:
        metadata = _build_lifecycle_metadata(normalized_snapshot)
        store.update_order(selected_client, metadata, event_type="d3_open_exit_lifecycle_metadata_updated")
        current_position = positions.get_position(selected_ticker) or position
        if current_position:
            positions.upsert_position(selected_ticker, metadata)
        report["applied_actions"].append("persist_lifecycle_idempotency_metadata")
        report["proposed_order_updates"] = {
            **_as_dict(report.get("proposed_order_updates")),
            **metadata,
        }
        report["proposed_position_updates"] = {
            **_as_dict(report.get("proposed_position_updates")),
            **metadata,
        }
    return _json_safe(report)


def build_phase_d3_open_exit_lifecycle_report(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    snapshot: Optional[Dict[str, Any]] = None,
    allow_coinbase_poll: bool = False,
    apply_local: bool = False,
    apply_ack: str = "",
) -> Dict[str, Any]:
    """Run D3 lifecycle preview, or lock the explicit local-apply boundary."""
    if not apply_local or str(apply_ack or "").strip() != D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK:
        return _build_phase_d3_open_exit_lifecycle_report_unlocked(
            ticker=ticker,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            linked_position_id=linked_position_id,
            order_store=order_store,
            state_store=state_store,
            coinbase_client=coinbase_client,
            snapshot=snapshot,
            allow_coinbase_poll=allow_coinbase_poll,
            apply_local=apply_local,
            apply_ack=apply_ack,
        )

    with process_lock(
        _d3_lifecycle_mutation_lock_path(order_store),
        allow_reentrant=True,
    ) as lock_info:
        report = _build_phase_d3_open_exit_lifecycle_report_unlocked(
            ticker=ticker,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            linked_position_id=linked_position_id,
            order_store=order_store,
            state_store=state_store,
            coinbase_client=coinbase_client,
            snapshot=snapshot,
            allow_coinbase_poll=allow_coinbase_poll,
            apply_local=True,
            apply_ack=apply_ack,
        )
    report["mutation_lock"] = {
        "acquired": True,
        "reentrant": bool(lock_info.get("reentrant")),
    }
    return report


__all__ = [
    "D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK",
    "D3_OPEN_EXIT_LIFECYCLE_PHASE",
    "build_phase_d3_open_exit_lifecycle_report",
    "iter_matching_open_d3_orders",
    "logical_position_id_candidates",
    "order_matches_logical_position",
    "reserved_base_for_matching_open_d3_orders",
    "scan_open_d3_exit_lifecycle_orders",
]
