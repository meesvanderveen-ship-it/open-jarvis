from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.order_store import FINAL_ORDER_STATUSES, OPEN_ORDER_STATUSES, OrderStore
from bot.phase_d2_position_executor import is_d2_manageable_open_position
from bot.phase_d3_controlled_live_exits import build_phase_d3_controlled_live_exit_report
from bot.state_store import StateStore

PHASE_C43_TINY_RESIDUAL_RECOVERY_PHASE = "C43_tiny_residual_position_recovery"
PHASE_C43_TINY_RESIDUAL_RECOVERY_ACK = (
    "I_UNDERSTAND_AND_APPROVE_PHASE_C43_TINY_RESIDUAL_POSITION_RECOVERY"
)
RECOVERY_REASON = "live_base_present_after_inventory_sync_tiny_residual_close"
POSITION_ACTION_DUST_RECOVERY_REASON = "live_base_present_after_position_action_dust_close"
RECOVERY_SOURCE = "read_only_coinbase_base_balance"
RECOVERY_SKIP_REASON = "phase_c43_pilot_position_kept_open_for_d2_d3_governance_review"
TINY_CLOSE_REASON = "inventory_sync_live_notional_below_min_trade_quote"
POSITION_ACTION_DUST_CLOSE_REASON = "position_closed_locally_dust_below_min_notional"
TARGET_TICKER = "BTC-USDC"
TARGET_CLIENT_ORDER_ID = "phasec-BTCUSDC-smoke-20260526003354"
TARGET_POSITION_ID = "76310097-849e-481c-b587-ba44bc3330fe"
ZERO = Decimal("0")
DEFAULT_LIVE_BASE_TOLERANCE = Decimal("0.0000000001")
ALLOWED_CLOSE_REASONS = {
    TINY_CLOSE_REASON,
    POSITION_ACTION_DUST_CLOSE_REASON,
}
OPEN_D3_RECOVERY_ALLOWED_REASON = "open_d3_live_exit_order_present_same_position"


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


def _parse_required_decimal(value: Any, field_name: str, blockers: list[str]) -> Optional[Decimal]:
    try:
        if value is None:
            blockers.append(f"{field_name}_missing")
            return None
        text = str(value).strip()
        if not text:
            blockers.append(f"{field_name}_missing")
            return None
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        blockers.append(f"{field_name}_unparseable")
        return None


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


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            row = json.loads(text)
            if isinstance(row, dict):
                rows.append(row)
    except Exception:
        return rows
    return rows


def _build_recovery_updates(position: Dict[str, Any], *, expected_live_base: Decimal) -> Dict[str, Any]:
    recovered_at = _now_iso()
    residual_base = _to_decimal(position.get("dust_residual_base"), "0")
    target_base = max(residual_base, expected_live_base, ZERO)
    residual_quote = _to_decimal(position.get("dust_residual_quote"), "0")
    close_reason = str(position.get("close_reason") or position.get("last_heartbeat_reason") or "").strip()
    recovery_reason = (
        POSITION_ACTION_DUST_RECOVERY_REASON
        if close_reason == POSITION_ACTION_DUST_CLOSE_REASON
        else RECOVERY_REASON
    )
    updates: Dict[str, Any] = {
        "status": "open",
        "position_size_base": str(target_base),
        "bot_managed_base": str(target_base),
        "position_size_quote": str(residual_quote),
        "monitoring_enabled": True,
        "last_heartbeat_status": "recovered_tiny_residual",
        "last_heartbeat_reason": recovery_reason,
        "recovered_from_closed_tiny_residual": True,
        "recovered_from_synthetic_tiny_residual_close": True,
        "recovered_from_position_action_dust_close": close_reason == POSITION_ACTION_DUST_CLOSE_REASON,
        "recovery_reason": recovery_reason,
        "recovery_source": RECOVERY_SOURCE,
        "recovery_at": recovered_at,
        "recovered_at": recovered_at,
        "tiny_residual_close_skipped_for_phase_c43_pilot_review": True,
        "tiny_residual_close_skip_reason": RECOVERY_SKIP_REASON,
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


def _compute_changes(current: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    changes: Dict[str, Dict[str, Any]] = {}
    for key, new_value in updates.items():
        old_value = current.get(key)
        if old_value != new_value:
            changes[key] = {"before": _json_safe(old_value), "after": _json_safe(new_value)}
    return changes


def _build_sell_evidence(
    *,
    order_store: OrderStore,
    ticker: str,
    position_id: str,
    order_events_path: Path,
    live_exit_orders_path: Path,
) -> Dict[str, Any]:
    def is_rejected_ghost(order: Dict[str, Any]) -> bool:
        status = str(order.get("status") or "").strip().lower()
        order_id = str(order.get("order_id") or "").strip()
        exchange_order_id = str(order.get("exchange_order_id") or "").strip()
        return status in {"rejected", "submit_rejected", "failed"} and not order_id and not exchange_order_id

    matched_orders: List[Dict[str, Any]] = []
    ignored_rejected_ghost_orders: List[Dict[str, Any]] = []
    for order in order_store.all_orders():
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if _normalize_ticker(order.get("ticker")) != ticker:
            continue
        linked = str(order.get("linked_position_id") or "").strip()
        if linked and linked != position_id:
            continue
        row = {
            "client_order_id": str(order.get("client_order_id") or ""),
            "status": str(order.get("status") or ""),
            "linked_position_id": linked,
            "execution_action": str(order.get("execution_action") or ""),
        }
        if is_rejected_ghost(order):
            ignored_rejected_ghost_orders.append(row)
            continue
        matched_orders.append(row)

    rejected_ghost_client_order_ids = {
        str(order.get("client_order_id") or "").strip()
        for order in order_store.all_orders()
        if isinstance(order, dict) and is_rejected_ghost(order)
    }

    event_hits: List[Dict[str, Any]] = []
    ignored_rejected_ghost_events: List[Dict[str, Any]] = []
    for row in _read_jsonl(order_events_path):
        order = row.get("order") if isinstance(row.get("order"), dict) else {}
        if not order:
            continue
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if _normalize_ticker(order.get("ticker") or order.get("product_id")) != ticker:
            continue
        linked = str(order.get("linked_position_id") or "").strip()
        if linked and linked != position_id:
            continue
        event_row = {
            "event_type": str(row.get("event_type") or ""),
            "client_order_id": str(order.get("client_order_id") or ""),
            "status": str(order.get("status") or ""),
            "linked_position_id": linked,
        }
        if event_row["client_order_id"] in rejected_ghost_client_order_ids:
            ignored_rejected_ghost_events.append(event_row)
            continue
        event_hits.append(event_row)

    live_exit_hits: List[Dict[str, Any]] = []
    for row in _read_jsonl(live_exit_orders_path):
        if bool(row.get("blocked")):
            continue
        if str(row.get("side") or "").strip().upper() != "SELL":
            continue
        if _normalize_ticker(row.get("ticker")) != ticker:
            continue
        linked = str(row.get("linked_position_id") or row.get("position_id") or "").strip()
        if linked and linked != position_id:
            continue
        if not bool(row.get("live_order_submitted") or row.get("executed") or row.get("submission_attempted")):
            continue
        client_order_id = str(row.get("client_order_id") or "").strip()
        if client_order_id and client_order_id in rejected_ghost_client_order_ids:
            continue
        live_exit_hits.append({
            "generated_at": row.get("generated_at"),
            "execution_status": row.get("execution_status"),
            "position_id": linked,
        })

    proof_exists = bool(matched_orders or event_hits or live_exit_hits)
    return {
        "proof_of_sell_exists": proof_exists,
        "matching_sell_orders": matched_orders,
        "matching_sell_order_events": event_hits,
        "matching_live_exit_events": live_exit_hits,
        "ignored_rejected_ghost_sell_orders": ignored_rejected_ghost_orders,
        "ignored_rejected_ghost_sell_events": ignored_rejected_ghost_events,
    }


def _classify_open_d3_exit_orders(
    *,
    orders: List[Dict[str, Any]],
    ticker: str,
    position_id: str,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    selected_position_id = str(position_id or "").strip()
    matching: List[Dict[str, Any]] = []
    nonmatching: List[Dict[str, Any]] = []
    for order in orders:
        row = dict(order or {})
        normalized = {
            "client_order_id": str(row.get("client_order_id") or ""),
            "status": str(row.get("status") or ""),
            "linked_position_id": str(row.get("linked_position_id") or ""),
            "side": str(row.get("side") or "").strip().upper(),
            "phase": str(row.get("phase") or ""),
            "exchange_order_id": str(row.get("exchange_order_id") or row.get("order_id") or "").strip(),
            "ticker": _normalize_ticker(row.get("ticker")),
        }
        is_matching = (
            normalized["ticker"] == selected_ticker
            and normalized["linked_position_id"] == selected_position_id
            and normalized["side"] == "SELL"
            and normalized["phase"] == "D3_controlled_live_reduce_only_exits"
            and bool(normalized["exchange_order_id"])
            and str(normalized["status"]).strip().lower() in OPEN_ORDER_STATUSES
        )
        if is_matching:
            matching.append(normalized)
        else:
            nonmatching.append(normalized)
    return {
        "matching_same_position_open_d3_exit_orders": matching,
        "nonmatching_open_d3_exit_orders": nonmatching,
        "exactly_one_matching_same_position_open_d3_exit_order": len(matching) == 1 and len(nonmatching) == 0,
        "matching_count": len(matching),
        "nonmatching_count": len(nonmatching),
    }


def _build_live_base_evidence(
    *,
    ticker: str,
    expected_live_base: Any,
    live_base_tolerance: Any,
    coinbase_client: Any,
) -> Dict[str, Any]:
    blockers: List[str] = []
    warnings: List[str] = []
    expected = _to_decimal(expected_live_base, "0")
    tolerance = max(ZERO, _to_decimal(live_base_tolerance, str(DEFAULT_LIVE_BASE_TOLERANCE)))
    live_snapshot: Dict[str, Any] = {}
    live_base_available: Optional[Decimal] = None
    live_base_total: Optional[Decimal] = None

    if expected <= ZERO:
        blockers.append("recovery_expected_live_base_nonpositive")

    if coinbase_client is None:
        blockers.append("recovery_coinbase_client_missing")
    else:
        try:
            live_snapshot = coinbase_client.get_spot_position(ticker)
        except Exception as exc:
            blockers.append("recovery_coinbase_client_error")
            warnings.append(f"recovery_coinbase_client_error_detail:{type(exc).__name__}")

    if coinbase_client is not None and not live_snapshot and "recovery_coinbase_client_error" not in blockers:
        blockers.append("recovery_live_base_snapshot_unparseable")

    if live_snapshot:
        live_base_available = _parse_required_decimal(
            live_snapshot.get("available_base_balance"),
            "recovery_live_base_available",
            blockers,
        )
        live_base_hold = _parse_required_decimal(
            live_snapshot.get("hold_base_balance"),
            "recovery_live_base_hold",
            blockers,
        )
        if live_base_available is not None and live_base_hold is not None:
            live_base_total = live_base_available + live_base_hold

    delta = None
    within_tolerance = False
    if live_base_available is not None:
        delta = live_base_available - expected
        within_tolerance = abs(delta) <= tolerance
        if not within_tolerance:
            blockers.append("recovery_live_base_available_mismatch")

    status = "recovery_live_base_evidence_ready" if not blockers else "recovery_live_base_evidence_blocked"
    return {
        "status": status,
        "coinbase_read_method": "get_spot_position",
        "read_only": True,
        "expected_live_base": str(expected),
        "live_base_tolerance": str(tolerance),
        "live_base_available": str(live_base_available) if live_base_available is not None else None,
        "live_base_total": str(live_base_total) if live_base_total is not None else None,
        "live_base_delta": str(delta) if delta is not None else None,
        "live_base_matches_expected": bool(within_tolerance),
        "coinbase_live_balance_snapshot": live_snapshot,
        "blockers": blockers,
        "warnings": warnings,
        "safety_policy": {
            "read_only_coinbase_balance_check_only": True,
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_replace": True,
            "does_not_mutate_state": True,
        },
    }


def build_phase_c43_tiny_residual_recovery_report(
    *,
    ticker: str,
    position_id: str,
    client_order_id: str,
    expected_live_base: Any = None,
    live_base_tolerance: Any = DEFAULT_LIVE_BASE_TOLERANCE,
    apply: bool = False,
    apply_ack: str = "",
    state_store: Optional[StateStore] = None,
    order_store: Optional[OrderStore] = None,
    coinbase_client: Any = None,
    order_events_path: str | Path = "logs/order_events.jsonl",
    live_exit_orders_path: str | Path = "logs/live_exit_orders.jsonl",
) -> Dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    state = state_store or StateStore()
    orders = order_store or OrderStore()
    position = state.get_position(ticker)
    linked_order = orders.get_order(client_order_id)
    report: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "phase": PHASE_C43_TINY_RESIDUAL_RECOVERY_PHASE,
        "ticker": ticker,
        "requested_position_id": str(position_id or "").strip(),
        "requested_client_order_id": str(client_order_id or "").strip(),
        "expected_live_base": str(expected_live_base) if expected_live_base is not None else "",
        "apply_requested": bool(apply),
        "dry_run": not bool(apply),
        "apply_ack_required": PHASE_C43_TINY_RESIDUAL_RECOVERY_ACK,
        "apply_ack_valid": not bool(apply) or str(apply_ack or "").strip() == PHASE_C43_TINY_RESIDUAL_RECOVERY_ACK,
        "state_write_performed": False,
        "coinbase_balance_check_available": coinbase_client is not None,
        "coinbase_balance_check_status": "not_requested",
        "warnings": [],
        "blockers": [],
        "safety_policy": {
            "dry_run_default": True,
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_replace": True,
            "does_not_modify_env": True,
            "does_not_bypass_live_exit_gate": True,
            "recovery_scope_single_phase_c43_tiny_residual_position_only": True,
        },
    }

    def require(condition: bool, blocker: str) -> None:
        if not condition:
            report["blockers"].append(blocker)

    require(ticker == TARGET_TICKER, "recovery_ticker_not_allowed")
    require(str(position_id or "").strip() == TARGET_POSITION_ID, "recovery_position_id_not_allowed")
    require(str(client_order_id or "").strip() == TARGET_CLIENT_ORDER_ID, "recovery_client_order_id_not_allowed")
    require(isinstance(position, dict), "recovery_position_missing")
    require(isinstance(linked_order, dict), "recovery_linked_order_missing")

    if isinstance(position, dict):
        report["position"] = {
            "status": position.get("status"),
            "order_id": position.get("order_id"),
            "phase_c43_client_order_id": position.get("phase_c43_client_order_id"),
            "phase_c43_exchange_order_id": position.get("phase_c43_exchange_order_id"),
            "entry_price": position.get("entry_price"),
            "position_size_base": position.get("position_size_base"),
            "position_size_quote": position.get("position_size_quote"),
            "bot_managed_base": position.get("bot_managed_base"),
            "dust_residual_base": position.get("dust_residual_base"),
            "dust_residual_quote": position.get("dust_residual_quote"),
            "close_reason": position.get("close_reason"),
            "synthetic_close_reason": position.get("synthetic_close_reason"),
            "synthetic_closed_at": position.get("synthetic_closed_at"),
            "last_heartbeat_status": position.get("last_heartbeat_status"),
            "tiny_residual_close_skipped_for_phase_c43_pilot_review": position.get(
                "tiny_residual_close_skipped_for_phase_c43_pilot_review"
            ),
            "tiny_residual_close_skip_reason": position.get("tiny_residual_close_skip_reason"),
        }
    if isinstance(linked_order, dict):
        report["linked_order"] = {
            "status": linked_order.get("status"),
            "filled_size_base": linked_order.get("filled_size_base"),
            "filled_quote_value": linked_order.get("filled_quote_value"),
            "position_created": linked_order.get("position_created"),
            "linked_position_id": linked_order.get("linked_position_id"),
            "d2_plan_created": linked_order.get("d2_plan_created"),
            "d3_preview_created": linked_order.get("d3_preview_created"),
        }

    if isinstance(position, dict):
        require(str(position.get("order_id") or "").strip() == str(position_id or "").strip(), "recovery_position_id_mismatch")
        require(
            str(position.get("phase_c43_client_order_id") or "").strip() == str(client_order_id or "").strip(),
            "recovery_client_order_id_mismatch",
        )
        require(bool(position.get("opened_via_phase_c43_live_order")), "recovery_not_opened_via_phase_c43")
        require(str(position.get("status") or "").strip().lower() == "closed", "recovery_position_not_closed")
        require(
            str(position.get("close_reason") or "").strip() in ALLOWED_CLOSE_REASONS,
            "recovery_close_reason_not_tiny_residual",
        )
        synthetic_close_reason = str(position.get("synthetic_close_reason") or "").strip()
        if synthetic_close_reason:
            require(
                synthetic_close_reason in ALLOWED_CLOSE_REASONS,
                "recovery_synthetic_close_reason_not_tiny_residual",
            )
        heartbeat_close_reason = str(position.get("last_heartbeat_reason") or "").strip()
        if heartbeat_close_reason:
            require(
                heartbeat_close_reason in ALLOWED_CLOSE_REASONS,
                "recovery_last_heartbeat_reason_not_tiny_residual",
            )
        require(_to_decimal(position.get("position_size_base"), "0") <= ZERO, "recovery_position_size_base_not_zero")
        require(_to_decimal(position.get("bot_managed_base"), "0") <= ZERO, "recovery_bot_managed_base_not_zero")
        require(
            max(_to_decimal(position.get("dust_residual_base"), "0"), _to_decimal(expected_live_base, "0")) > ZERO,
            "recovery_dust_residual_base_nonpositive",
        )
    if isinstance(linked_order, dict):
        require(str(linked_order.get("status") or "").strip().lower() == "filled", "recovery_linked_order_not_filled")
        require(bool(linked_order.get("position_created")), "recovery_linked_order_position_not_created")
        require(
            str(linked_order.get("linked_position_id") or "").strip() == str(position_id or "").strip(),
            "recovery_linked_position_id_mismatch",
        )
        require(
            bool(linked_order.get("d2_plan_created")) or bool(linked_order.get("d3_preview_created")),
            "recovery_linked_order_missing_d2_d3_preview_markers",
        )

    open_c43_entry_orders = orders.open_entry_orders(ticker=ticker)
    report["open_c43_entry_orders"] = {
        "count": len(open_c43_entry_orders),
        "orders": [
            {
                "client_order_id": str(order.get("client_order_id") or ""),
                "status": str(order.get("status") or ""),
            }
            for order in open_c43_entry_orders
        ],
    }
    require(len(open_c43_entry_orders) == 0, "recovery_open_c43_entry_order_exists")

    open_d3_exit_orders = orders.open_exit_orders(ticker=ticker)
    open_d3_classification = _classify_open_d3_exit_orders(
        orders=open_d3_exit_orders,
        ticker=ticker,
        position_id=str(position_id or "").strip(),
    )
    report["open_d3_exit_orders"] = {
        "count": len(open_d3_exit_orders),
        "orders": open_d3_classification["matching_same_position_open_d3_exit_orders"]
        + open_d3_classification["nonmatching_open_d3_exit_orders"],
        "matching_same_position_open_d3_exit_orders": open_d3_classification["matching_same_position_open_d3_exit_orders"],
        "nonmatching_open_d3_exit_orders": open_d3_classification["nonmatching_open_d3_exit_orders"],
    }
    allow_open_d3_recovery = bool(open_d3_classification["exactly_one_matching_same_position_open_d3_exit_order"])
    report["open_d3_exit_recovery_context"] = {
        "allowed_for_recovery": allow_open_d3_recovery,
        "reason": OPEN_D3_RECOVERY_ALLOWED_REASON if allow_open_d3_recovery else "",
        "matching_count": open_d3_classification["matching_count"],
        "nonmatching_count": open_d3_classification["nonmatching_count"],
    }
    require(
        len(open_d3_exit_orders) == 0 or allow_open_d3_recovery,
        "recovery_open_d3_exit_order_exists",
    )

    sell_evidence = _build_sell_evidence(
        order_store=orders,
        ticker=ticker,
        position_id=str(position_id or "").strip(),
        order_events_path=Path(order_events_path),
        live_exit_orders_path=Path(live_exit_orders_path),
    )
    if allow_open_d3_recovery:
        matching_open_clients = {
            str(row.get("client_order_id") or "").strip()
            for row in open_d3_classification["matching_same_position_open_d3_exit_orders"]
        }
        sell_evidence["matching_sell_orders"] = [
            row for row in sell_evidence["matching_sell_orders"]
            if str(row.get("client_order_id") or "").strip() not in matching_open_clients
        ]
        sell_evidence["matching_sell_order_events"] = [
            row for row in sell_evidence["matching_sell_order_events"]
            if str(row.get("client_order_id") or "").strip() not in matching_open_clients
        ]
        sell_evidence["matching_live_exit_events"] = [
            row for row in sell_evidence["matching_live_exit_events"]
            if str(row.get("position_id") or "").strip() != str(position_id or "").strip()
        ]
        sell_evidence["allowed_open_d3_exit_orders_ignored_for_recovery"] = (
            open_d3_classification["matching_same_position_open_d3_exit_orders"]
        )
        sell_evidence["proof_of_sell_exists"] = bool(
            sell_evidence["matching_sell_orders"]
            or sell_evidence["matching_sell_order_events"]
            or sell_evidence["matching_live_exit_events"]
        )
    report["sell_evidence"] = sell_evidence
    require(not sell_evidence["proof_of_sell_exists"], "recovery_sell_evidence_detected")

    live_base_evidence = _build_live_base_evidence(
        ticker=ticker,
        expected_live_base=expected_live_base,
        live_base_tolerance=live_base_tolerance,
        coinbase_client=coinbase_client,
    )
    if allow_open_d3_recovery:
        expected_total = _to_decimal(expected_live_base, "0")
        tolerance_total = max(ZERO, _to_decimal(live_base_tolerance, str(DEFAULT_LIVE_BASE_TOLERANCE)))
        live_total = _to_decimal(live_base_evidence.get("live_base_total"), "0")
        total_delta = live_total - expected_total
        total_match = expected_total > ZERO and abs(total_delta) <= tolerance_total
        live_base_evidence["open_d3_expected_total_match"] = total_match
        live_base_evidence["open_d3_live_base_total_delta"] = str(total_delta)
        if total_match:
            live_base_evidence["live_base_matches_expected"] = True
            live_base_evidence["status"] = "recovery_live_base_evidence_ready"
            live_base_evidence["blockers"] = [
                blocker
                for blocker in list(live_base_evidence.get("blockers") or [])
                if blocker != "recovery_live_base_available_mismatch"
            ]
            report["blockers"] = [
                blocker
                for blocker in list(report.get("blockers") or [])
                if blocker != "recovery_live_base_available_mismatch"
            ]
    report["live_base_evidence"] = live_base_evidence
    report["coinbase_balance_check_available"] = bool(coinbase_client is not None)
    report["coinbase_balance_check_status"] = str(live_base_evidence.get("status") or "not_requested")
    report["warnings"].extend(list(live_base_evidence.get("warnings") or []))
    for blocker in live_base_evidence.get("blockers") or []:
        require(False, str(blocker))

    updates = _build_recovery_updates(
        position or {},
        expected_live_base=_to_decimal(expected_live_base, "0"),
    )
    changes = _compute_changes(position or {}, updates)
    report["proposed_updates"] = updates
    report["proposed_changes"] = changes
    report["d2_manageable_after_recovery"] = is_d2_manageable_open_position(
        {**(position or {}), **updates},
        ticker=ticker,
    )
    preview_position = {**(position or {}), **updates}
    report["d3_preview_after_recovery"] = build_phase_d3_controlled_live_exit_report(
        cfg=type("Cfg", (), {
            "enable_phase_d3_controlled_live_exits": True,
            "enable_phase_d3_actual_exit_submit": False,
            "enable_live_exit_orders": False,
            "autonomous_allow_exits": False,
            "phase_c_disable_exit_limit_orders": True,
        })(),
        ticker=ticker,
        state_store=state,
        order_store=orders,
        position=preview_position,
        plan=None,
        exchange_rules=None,
        coinbase_client=None,
        submit_live=False,
    )

    if apply:
        if not report["apply_ack_valid"]:
            require(False, "recovery_apply_ack_required")
        if not report["blockers"]:
            updated = state.upsert_position(ticker, updates)
            report["state_write_performed"] = True
            report["applied_position"] = updated
            report["status"] = "phase_c43_tiny_residual_recovery_applied"
        else:
            report["status"] = "phase_c43_tiny_residual_recovery_blocked"
    else:
        report["status"] = "phase_c43_tiny_residual_recovery_dry_run"

    return _json_safe(report)


__all__ = [
    "PHASE_C43_TINY_RESIDUAL_RECOVERY_ACK",
    "PHASE_C43_TINY_RESIDUAL_RECOVERY_PHASE",
    "POSITION_ACTION_DUST_CLOSE_REASON",
    "POSITION_ACTION_DUST_RECOVERY_REASON",
    "RECOVERY_SOURCE",
    "RECOVERY_REASON",
    "RECOVERY_SKIP_REASON",
    "TARGET_CLIENT_ORDER_ID",
    "TARGET_POSITION_ID",
    "TARGET_TICKER",
    "TINY_CLOSE_REASON",
    "build_phase_c43_tiny_residual_recovery_report",
]
