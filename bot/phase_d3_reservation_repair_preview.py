from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


D3_RESERVATION_DRIFT_REPAIR_PHASE = "D3_reservation_drift_repair_preview"
D3_RESERVATION_DRIFT_REPAIR_ACK = "I_UNDERSTAND_AND_APPROVE_D3_RESERVATION_DRIFT_REPAIR_APPLY"
ZERO = Decimal("0")
OPEN_STATUSES = {"planned", "pending", "submitted", "open", "partially_filled", "partial", "cancel_pending", "replace_pending"}
TERMINAL_STATUSES = {"cancelled", "canceled", "expired", "rejected"}


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
        return Decimal(text if text else default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _normalize_status(value: Any, *, filled_base: Any = "0") -> str:
    status = str(value or "").strip().lower()
    aliases = {
        "submitted": "open",
        "pending": "open",
        "open": "open",
        "partially_filled": "partial",
        "partial": "partial",
        "filled": "filled",
        "done": "filled" if _to_decimal(filled_base) > ZERO else "cancelled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
    }
    return aliases.get(status, status or "unknown")


def load_json_file(path: str | Path) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def write_json_file(path: str | Path, payload: Dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def orders_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_orders = payload.get("orders", payload)
    if isinstance(raw_orders, dict):
        return [dict(order) for order in raw_orders.values() if isinstance(order, dict)]
    if isinstance(raw_orders, list):
        return [dict(order) for order in raw_orders if isinstance(order, dict)]
    return []


def position_from_payload(payload: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker)
    raw_positions = payload.get("positions", payload)
    if isinstance(raw_positions, dict):
        direct = raw_positions.get(selected) or raw_positions.get(ticker)
        if isinstance(direct, dict):
            return dict(direct)
        for position in raw_positions.values():
            if isinstance(position, dict) and _normalize_ticker(position.get("ticker")) == selected:
                return dict(position)
    if isinstance(raw_positions, list):
        for position in raw_positions:
            if isinstance(position, dict) and _normalize_ticker(position.get("ticker")) == selected:
                return dict(position)
    return {}


def replace_position_in_payload(payload: Dict[str, Any], ticker: str, position: Dict[str, Any]) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker)
    out = dict(payload)
    if isinstance(out.get("positions"), dict):
        positions = dict(out["positions"])
        positions[selected] = dict(position)
        out["positions"] = positions
        return out
    out[selected] = dict(position)
    return out


def find_order(
    orders: Iterable[Dict[str, Any]],
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    for order in orders:
        if _normalize_ticker(order.get("ticker") or order.get("product_id")) != selected_ticker:
            continue
        client_match = str(order.get("client_order_id") or "").strip() == str(client_order_id or "").strip()
        exchange_match = str(order.get("exchange_order_id") or order.get("order_id") or "").strip() == str(exchange_order_id or "").strip()
        if client_match or exchange_match:
            return dict(order)
    return {}


def open_d3_exit_orders(
    orders: Iterable[Dict[str, Any]],
    *,
    ticker: str,
    linked_position_id: str,
) -> List[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    selected_position = str(linked_position_id or "").strip()
    out: List[Dict[str, Any]] = []
    for order in orders:
        status = str(order.get("status") or "").strip().lower()
        if _normalize_ticker(order.get("ticker") or order.get("product_id")) != selected_ticker:
            continue
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if str(order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
            continue
        if status not in OPEN_STATUSES:
            continue
        if selected_position and str(order.get("linked_position_id") or "").strip() != selected_position:
            continue
        out.append(dict(order))
    return out


def _status_route(status: str, filled_base: Decimal, fill_count: int) -> str:
    if status in {"partial", "filled"} or filled_base > ZERO or fill_count > 0:
        return "route_to_d3_lifecycle_apply"
    if status in {"cancelled", "expired", "rejected"}:
        return "route_to_d3_terminal_closeout"
    if status == "open":
        return "open_zero_fill_reservation_check"
    return "status_uncertain_no_repair"


def build_phase_d3_reservation_repair_preview(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    orders_payload: Dict[str, Any],
    positions_payload: Dict[str, Any],
    apply: bool = False,
    repair_ack: str = "",
    now_iso: str | None = None,
) -> Tuple[Dict[str, Any], Dict[str, Any] | None]:
    selected_ticker = _normalize_ticker(ticker)
    orders = orders_from_payload(orders_payload)
    position = position_from_payload(positions_payload, selected_ticker)
    target_order = find_order(
        orders,
        ticker=selected_ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
    )
    linked_position_id = str((target_order or {}).get("linked_position_id") or "").strip()
    open_exits = open_d3_exit_orders(orders, ticker=selected_ticker, linked_position_id=linked_position_id)

    filled_base = _to_decimal((target_order or {}).get("filled_base") or (target_order or {}).get("filled_size"), "0")
    fill_count = _to_int((target_order or {}).get("fill_count"), 0)
    status = _normalize_status((target_order or {}).get("status"), filled_base=filled_base)
    route = _status_route(status, filled_base, fill_count)
    remaining_size = _to_decimal((target_order or {}).get("remaining_size") or (target_order or {}).get("size_base"), "0")
    current_reserved = _to_decimal(position.get("reserved_base_open_exit_orders"), "0")
    position_size_base = _to_decimal(position.get("position_size_base"), "0")
    bot_managed_base = _to_decimal(position.get("bot_managed_base") or position.get("position_size_base"), "0")
    required_reserved = remaining_size if route == "open_zero_fill_reservation_check" else ZERO
    proposed_reserved = current_reserved if current_reserved >= required_reserved else required_reserved
    available_after = bot_managed_base - proposed_reserved
    apply_ack_valid = not apply or str(repair_ack or "").strip() == D3_RESERVATION_DRIFT_REPAIR_ACK

    blockers: List[str] = []
    warnings: List[str] = []
    if not target_order:
        blockers.append("open_d3_exit_order_not_found")
    if not position:
        blockers.append("position_not_found")
    if target_order and str(target_order.get("linked_position_id") or "").strip() == "":
        blockers.append("linked_position_id_missing")
    if len(open_exits) > 1:
        blockers.append("duplicate_open_d3_exit_orders_for_position")
    if route == "route_to_d3_lifecycle_apply":
        blockers.append("fill_evidence_route_to_d3_lifecycle_apply")
    elif route == "route_to_d3_terminal_closeout":
        blockers.append("terminal_evidence_route_to_d3_terminal_closeout")
    elif route == "status_uncertain_no_repair":
        blockers.append("order_status_uncertain_no_repair_without_lifecycle_evidence")
    if route == "open_zero_fill_reservation_check" and remaining_size <= ZERO:
        blockers.append("open_exit_remaining_size_missing_or_zero")
    if str(position.get("status") or "").strip().lower() != "open":
        blockers.append("position_not_open")
    if position_size_base < ZERO or bot_managed_base < ZERO or current_reserved < ZERO:
        blockers.append("negative_position_or_reservation_not_allowed")
    if bot_managed_base < proposed_reserved:
        blockers.append("insufficient_bot_managed_base_for_required_reservation")
    if available_after < ZERO:
        blockers.append("available_base_after_reservations_negative")
    if position_size_base < ZERO:
        blockers.append("insufficient_position_size_base")
    if position_size_base != available_after and route == "open_zero_fill_reservation_check":
        warnings.append("position_size_base_not_equal_available_after_reservations_after")
    if current_reserved > required_reserved and route == "open_zero_fill_reservation_check":
        warnings.append("current_reserved_base_exceeds_required_open_exit_remaining_size")
    if apply and not apply_ack_valid:
        blockers.append("reservation_drift_repair_apply_ack_required")

    drift_detected = current_reserved < required_reserved
    coherent = not blockers and not drift_detected
    preview_ready = not blockers and drift_detected
    status_value = "d3_reservation_repair_blocked"
    suggested_action = "no_apply"
    updated_positions_payload: Dict[str, Any] | None = None
    state_write_performed = False
    would_write_state = False

    if blockers:
        status_value = "d3_reservation_repair_blocked"
    elif apply:
        repaired_position = dict(position)
        repaired_position["reserved_base_open_exit_orders"] = str(proposed_reserved)
        updated_positions_payload = replace_position_in_payload(positions_payload, selected_ticker, repaired_position)
        state_write_performed = True
        would_write_state = True
        status_value = "d3_reservation_repair_applied"
        suggested_action = "applied"
    elif preview_ready:
        status_value = "d3_reservation_repair_preview_ready"
        suggested_action = "preview_repair_requires_ack"
    elif coherent:
        status_value = "d3_reservation_repair_noop_coherent"
        suggested_action = "no_op"

    report = {
        "generated_at": now_iso or _now_iso(),
        "phase": D3_RESERVATION_DRIFT_REPAIR_PHASE,
        "status": status_value,
        "suggested_action": suggested_action,
        "ticker": selected_ticker,
        "client_order_id": str(client_order_id or ""),
        "exchange_order_id": str(exchange_order_id or ""),
        "linked_position_id": linked_position_id,
        "order_found": bool(target_order),
        "position_found": bool(position),
        "local_order_status": status,
        "lifecycle_route": route,
        "fill_count": fill_count,
        "filled_base": str(filled_base),
        "open_d3_exit_count": len(open_exits),
        "position_status": str(position.get("status") or ""),
        "position_size_base": str(position.get("position_size_base") or "0"),
        "bot_managed_base": str(position.get("bot_managed_base") or "0"),
        "current_reserved_base": str(current_reserved),
        "required_reserved_base": str(required_reserved),
        "open_exit_remaining_size": str(remaining_size),
        "proposed_reserved_base_after": str(proposed_reserved),
        "available_base_after_reservations_after": str(available_after),
        "drift_detected": bool(drift_detected),
        "position_remains_open": str(position.get("status") or "").strip().lower() == "open",
        "duplicate_open_exit_detected": len(open_exits) > 1,
        "oversell_detected": bool(bot_managed_base < proposed_reserved or available_after < ZERO),
        "would_write_state": bool(would_write_state),
        "apply_requested": bool(apply),
        "apply_allowed": bool(apply and apply_ack_valid and not blockers),
        "required_ack": D3_RESERVATION_DRIFT_REPAIR_ACK,
        "ack_valid": bool(apply_ack_valid),
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "no_coinbase_call": True,
        "no_live_action": True,
        "lifecycle_apply_performed": False,
        "state_write_performed": bool(state_write_performed),
    }
    return _json_safe(report), updated_positions_payload


def build_phase_d3_reservation_repair_preview_from_files(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    orders_file: str | Path,
    positions_file: str | Path,
    apply: bool = False,
    repair_ack: str = "",
) -> Dict[str, Any]:
    orders_payload = load_json_file(orders_file)
    positions_payload = load_json_file(positions_file)
    report, updated_positions_payload = build_phase_d3_reservation_repair_preview(
        ticker=ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        orders_payload=orders_payload,
        positions_payload=positions_payload,
        apply=apply,
        repair_ack=repair_ack,
    )
    if updated_positions_payload is not None:
        write_json_file(positions_file, updated_positions_payload)
    report["orders_file"] = str(orders_file)
    report["positions_file"] = str(positions_file)
    return report


__all__ = [
    "D3_RESERVATION_DRIFT_REPAIR_ACK",
    "D3_RESERVATION_DRIFT_REPAIR_PHASE",
    "build_phase_d3_reservation_repair_preview",
    "build_phase_d3_reservation_repair_preview_from_files",
]
