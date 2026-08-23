from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d45_exit_operations_report import (
    FILL_APPLY_ROUTE,
    TERMINAL_CLOSEOUT_ROUTE,
    evaluate_trigger_policy,
    target_distance_band,
)
from bot.phase_d5_execution_metrics import build_phase_d5_execution_metrics_report


D45_HISTORICAL_EXIT_OPERATIONS_PHASE = "D45_historical_exit_operations_report_v1"
OPEN_EXIT_STATUSES = {"planned", "pending", "submitted", "open", "partially_filled", "partial", "cancel_pending", "replace_pending"}
ZERO = Decimal("0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


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
        if value is None or str(value).strip() == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_status(value: Any, *, filled_base: Any = "0") -> str:
    status = str(value or "").strip().lower()
    aliases = {
        "submitted": "open",
        "open": "open",
        "partial": "partial",
        "partially_filled": "partial",
        "filled": "filled",
        "done": "filled" if _to_decimal(filled_base) > ZERO else "cancelled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
    }
    return aliases.get(status, status or "unknown")


def _load_json(path: str | Path) -> Dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _orders_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    orders = payload.get("orders", payload)
    if isinstance(orders, dict):
        return [dict(v) for v in orders.values() if isinstance(v, dict)]
    if isinstance(orders, list):
        return [dict(v) for v in orders if isinstance(v, dict)]
    return []


def _position_from_payload(payload: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    positions = payload.get("positions", payload)
    if isinstance(positions, dict):
        direct = positions.get(ticker)
        if isinstance(direct, dict):
            return dict(direct)
        for position in positions.values():
            if isinstance(position, dict) and str(position.get("ticker") or "").upper() == ticker.upper():
                return dict(position)
    return {}


def _find_order(orders: Iterable[Dict[str, Any]], *, client_order_id: str = "", exchange_order_id: str = "") -> Dict[str, Any]:
    selected_client = str(client_order_id or "").strip()
    selected_exchange = str(exchange_order_id or "").strip()
    for order in orders:
        if selected_client and str(order.get("client_order_id") or "").strip() == selected_client:
            return dict(order)
        exchange = str(order.get("exchange_order_id") or order.get("order_id") or "").strip()
        if selected_exchange and exchange == selected_exchange:
            return dict(order)
    return {}


def _open_exits_for_position(orders: Iterable[Dict[str, Any]], *, ticker: str, linked_position_id: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for order in orders:
        if str(order.get("ticker") or order.get("product_id") or "").upper() != ticker.upper():
            continue
        if str(order.get("side") or "").upper() != "SELL":
            continue
        if str(order.get("phase") or "") != "D3_controlled_live_reduce_only_exits":
            continue
        if str(order.get("linked_position_id") or "").strip() != str(linked_position_id or "").strip():
            continue
        if str(order.get("status") or "").strip().lower() in OPEN_EXIT_STATUSES:
            out.append(dict(order))
    return out


def _read_matching_events(path: str | Path, ids: Iterable[str], *, max_events: int = 50) -> List[Dict[str, Any]]:
    if not path or not Path(path).exists():
        return []
    needles = {str(value) for value in ids if str(value or "").strip()}
    if not needles:
        return []
    matched: List[Dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text or not any(needle in text for needle in needles):
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict):
                matched.append(event)
    return matched[-max_events:]


def _order_summary(order: Dict[str, Any]) -> Dict[str, Any]:
    filled_base = str(order.get("filled_base") or order.get("filled_size") or "0")
    return {
        "ticker": str(order.get("ticker") or order.get("product_id") or ""),
        "client_order_id": str(order.get("client_order_id") or ""),
        "exchange_order_id": str(order.get("exchange_order_id") or order.get("order_id") or ""),
        "linked_position_id": str(order.get("linked_position_id") or ""),
        "status": str(order.get("status") or ""),
        "normalized_status": _normalize_status(order.get("status"), filled_base=filled_base),
        "limit_price": str(order.get("limit_price") or ""),
        "size_base": str(order.get("size_base") or order.get("remaining_size") or ""),
        "remaining_size": str(order.get("remaining_size") or order.get("size_base") or ""),
        "filled_base": filled_base,
        "filled_quote": str(order.get("filled_quote") or "0"),
        "fill_count": _to_int(order.get("fill_count"), 0),
        "post_only": bool(order.get("post_only", False)),
        "reduce_only_local": bool(order.get("reduce_only_local", False)),
        "created_at": str(order.get("created_at") or order.get("submitted_at") or ""),
        "updated_at": str(order.get("updated_at") or ""),
        "closed_at": str(order.get("closed_at") or order.get("cancelled_at") or order.get("finalized_at") or ""),
    }


def _timeline(active: Dict[str, Any], old: Dict[str, Any], events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if old:
        rows.append({
            "timestamp": str(old.get("created_at") or ""),
            "event": "original_tp1_submitted",
            "client_order_id": str(old.get("client_order_id") or ""),
            "exchange_order_id": str(old.get("exchange_order_id") or old.get("order_id") or ""),
            "price": str(old.get("limit_price") or ""),
        })
        rows.append({
            "timestamp": str(old.get("cancelled_at") or old.get("closed_at") or old.get("finalized_at") or ""),
            "event": "original_tp1_cancelled_zero_fill",
            "client_order_id": str(old.get("client_order_id") or ""),
            "exchange_order_id": str(old.get("exchange_order_id") or old.get("order_id") or ""),
            "price": str(old.get("limit_price") or ""),
        })
    if active:
        rows.append({
            "timestamp": str(active.get("submitted_at") or active.get("created_at") or ""),
            "event": "replacement_tp1_submitted",
            "client_order_id": str(active.get("client_order_id") or ""),
            "exchange_order_id": str(active.get("exchange_order_id") or active.get("order_id") or ""),
            "price": str(active.get("limit_price") or ""),
            "replacement_of_exchange_order_id": str(active.get("replacement_of_exchange_order_id") or ""),
        })
    for event in events:
        rows.append({
            "timestamp": str(event.get("generated_at") or event.get("timestamp") or ""),
            "event": str(event.get("event_type") or event.get("status") or "matched_log_event"),
            "source": "order_events",
        })
    rows.sort(key=lambda row: str(row.get("timestamp") or ""))
    return rows


def _route_for_status(status: str, *, filled_base: Any = "0", fill_count: Any = 0) -> Dict[str, str]:
    normalized = _normalize_status(status, filled_base=filled_base)
    if normalized == "open" and _to_decimal(filled_base) <= ZERO and _to_int(fill_count) == 0:
        return {"branch": "open_keep_open", "route": "wait_for_trigger"}
    if normalized in {"partial", "filled"} or _to_decimal(filled_base) > ZERO or _to_int(fill_count) > 0:
        return {"branch": "fill_evidence", "route": FILL_APPLY_ROUTE}
    if normalized in {"cancelled", "expired", "rejected"}:
        return {"branch": "terminal_evidence", "route": TERMINAL_CLOSEOUT_ROUTE}
    return {"branch": "fail_closed", "route": "p0_or_poll_uncertainty_review"}


def _local_safety(
    *,
    active: Dict[str, Any],
    old: Dict[str, Any],
    position: Dict[str, Any],
    open_exits: List[Dict[str, Any]],
) -> Dict[str, Any]:
    blockers: List[str] = []
    active_remaining = _to_decimal(active.get("remaining_size") or active.get("size_base"), "0")
    reserved = _to_decimal(position.get("reserved_base_open_exit_orders"), "0")
    manageable = max(
        _to_decimal(position.get("bot_managed_base"), "0"),
        _to_decimal(position.get("position_size_base"), "0"),
    )
    if not active:
        blockers.append("active_replacement_order_not_found")
    if not old:
        blockers.append("old_replaced_order_not_found")
    if old and str(old.get("status") or "").lower() not in {"cancelled", "canceled"}:
        blockers.append("old_order_not_cancelled")
    if len(open_exits) != 1:
        blockers.append("open_exit_count_not_exactly_one")
    if active_remaining > ZERO and reserved != active_remaining:
        blockers.append("reservation_not_equal_active_remaining")
    duplicate = len(open_exits) > 1
    oversell = manageable > ZERO and reserved > manageable
    if oversell:
        blockers.append("reserved_base_exceeds_manageable_base")
    return {
        "status": "coherent" if not blockers else "blocked_p0_review_required",
        "blockers": blockers,
        "exactly_one_open_exit": len(open_exits) == 1,
        "open_exit_count": len(open_exits),
        "reservation_coherent": active_remaining > ZERO and reserved == active_remaining,
        "reserved_base_open_exit_orders": str(position.get("reserved_base_open_exit_orders") or ""),
        "active_remaining_size": str(active.get("remaining_size") or active.get("size_base") or ""),
        "duplicate_open_exit_detected": duplicate,
        "oversell_detected": oversell,
        "old_order_not_open": bool(old) and str(old.get("status") or "").lower() not in OPEN_EXIT_STATUSES,
    }


def build_phase_d45_historical_exit_operations_report(
    *,
    orders_payload: Dict[str, Any],
    positions_payload: Dict[str, Any],
    ticker: str,
    active_client_order_id: str,
    active_exchange_order_id: str,
    linked_position_id: str,
    old_client_order_id: str = "",
    old_exchange_order_id: str = "",
    market_mid: Any = "",
    event_log_path: str | Path = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now_dt = now or _now()
    orders = _orders_from_payload(orders_payload)
    position = _position_from_payload(positions_payload, ticker)
    active = _find_order(orders, client_order_id=active_client_order_id, exchange_order_id=active_exchange_order_id)
    if not old_client_order_id and active:
        old_client_order_id = str(active.get("replacement_of_client_order_id") or "")
    if not old_exchange_order_id and active:
        old_exchange_order_id = str(active.get("replacement_of_exchange_order_id") or "")
    old = _find_order(orders, client_order_id=old_client_order_id, exchange_order_id=old_exchange_order_id)
    open_exits = _open_exits_for_position(orders, ticker=ticker, linked_position_id=linked_position_id)
    ids = [active_client_order_id, active_exchange_order_id, old_client_order_id, old_exchange_order_id]
    events = _read_matching_events(event_log_path, ids) if event_log_path else []
    safety = _local_safety(active=active, old=old, position=position, open_exits=open_exits)

    lifecycle_event = {
        "lifecycle_status": _normalize_status(active.get("status"), filled_base=active.get("filled_base")),
        "submitted_at": active.get("submitted_at") or active.get("created_at") or "",
        "first_seen_open_at": active.get("created_at") or active.get("submitted_at") or "",
        "filled_base": active.get("filled_base") or "0",
        "filled_quote": active.get("filled_quote") or "0",
        "fill_count": active.get("fill_count") or 0,
        "planned_exit_price": active.get("limit_price") or "",
        "planned_size_base": active.get("size_base") or active.get("remaining_size") or "",
    }
    d5 = build_phase_d5_execution_metrics_report(
        lifecycle_event=lifecycle_event,
        plan_fields={
            "planned_entry_price": str(position.get("entry_price") or ""),
            "planned_exit_price": str(active.get("limit_price") or ""),
            "planned_size_base": str(active.get("size_base") or active.get("remaining_size") or ""),
        },
        market_refs={"decision_mid": market_mid, "decision_best_bid": market_mid} if market_mid else None,
        now=now_dt,
    )
    local_d45_projection = {
        "recommended_operator_action": "wait_for_trigger" if not safety["blockers"] else "blocked_p0_review_required",
        "open_d3_exit_count_for_position": safety["open_exit_count"],
        "reserved_base_open_exit_orders": safety["reserved_base_open_exit_orders"],
        "remaining_size": safety["active_remaining_size"],
        "blockers": list(safety["blockers"]),
    }
    trigger = evaluate_trigger_policy(
        local_report=local_d45_projection,
        limit_price=active.get("limit_price") or "",
        market_mid=market_mid,
    )
    active_route = _route_for_status(
        active.get("status") or "unknown",
        filled_base=active.get("filled_base") or "0",
        fill_count=active.get("fill_count") or 0,
    )
    report = {
        "generated_at": now_dt.isoformat(),
        "phase": D45_HISTORICAL_EXIT_OPERATIONS_PHASE,
        "status": "d45_historical_exit_operations_report_ready" if not safety["blockers"] else "d45_historical_exit_operations_blocked_p0",
        "ticker": ticker,
        "linked_position_id": linked_position_id,
        "active_order": _order_summary(active),
        "old_order": _order_summary(old),
        "historical_lifecycle_summary": {
            "original_tp1_price": str(old.get("limit_price") or ""),
            "replacement_tp1_price": str(active.get("limit_price") or ""),
            "old_order_cancelled_zero_fill": bool(old)
            and str(old.get("status") or "").lower() in {"cancelled", "canceled"}
            and _to_decimal(old.get("filled_base") or old.get("filled_size"), "0") <= ZERO
            and _to_int(old.get("fill_count"), 0) == 0,
            "replacement_is_active": bool(active) and str(active.get("status") or "").lower() in OPEN_EXIT_STATUSES,
            "replacement_of_exchange_order_id": str(active.get("replacement_of_exchange_order_id") or ""),
        },
        "timeline": _timeline(active, old, events),
        "local_state": safety,
        "d5_no_fill_stale_metrics": {
            "no_fill_duration_seconds": d5.get("no_fill_duration_seconds", ""),
            "stale_order_age_seconds": d5.get("stale_order_age_seconds", ""),
            "target_distance_abs": d5.get("target_distance_abs", ""),
            "target_distance_pct": d5.get("target_distance_pct", ""),
            "target_distance_band": d5.get("target_distance_band", ""),
            "no_fill_recommendation_label": d5.get("no_fill_recommendation_label", ""),
            "learning_to_execution_allowed": bool(d5.get("learning_to_execution_allowed", False)),
            "report_only": True,
        },
        "market_distance": target_distance_band(limit_price=active.get("limit_price") or "", market_mid=market_mid),
        "trigger_policy": trigger,
        "current_route": active_route,
        "next_valid_routes": {
            "OPEN/open zero fills": "keep_open / wait_for_trigger",
            "PARTIAL/FILLED": FILL_APPLY_ROUTE,
            "CANCELLED/EXPIRED/REJECTED": TERMINAL_CLOSEOUT_ROUTE,
            "safety drift": "blocked_p0_review_required",
        },
        "event_log_entries_included": len(events),
        "no_coinbase_call": True,
        "no_live_action": True,
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "state_write_performed": False,
        "learning_to_execution_allowed": False,
    }
    return _json_safe(report)


def build_report_from_files(
    *,
    orders_file: str | Path,
    positions_file: str | Path,
    ticker: str,
    active_client_order_id: str,
    active_exchange_order_id: str,
    linked_position_id: str,
    old_client_order_id: str = "",
    old_exchange_order_id: str = "",
    market_mid: Any = "",
    event_log_path: str | Path = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    return build_phase_d45_historical_exit_operations_report(
        orders_payload=_load_json(orders_file),
        positions_payload=_load_json(positions_file),
        ticker=ticker,
        active_client_order_id=active_client_order_id,
        active_exchange_order_id=active_exchange_order_id,
        linked_position_id=linked_position_id,
        old_client_order_id=old_client_order_id,
        old_exchange_order_id=old_exchange_order_id,
        market_mid=market_mid,
        event_log_path=event_log_path,
        now=now,
    )


__all__ = [
    "D45_HISTORICAL_EXIT_OPERATIONS_PHASE",
    "build_phase_d45_historical_exit_operations_report",
    "build_report_from_files",
]
