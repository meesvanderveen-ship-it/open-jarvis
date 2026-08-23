from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional


D4_CANCEL_REPLACE_PLANNER_PHASE = "D4_cancel_replace_dry_run_planner"
D4_CANCEL_REPLACE_REQUIRED_ACK = "I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT"
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


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _normalize_order_status(value: Any, *, filled_base: Any = "0") -> str:
    status = str(value or "").strip().lower()
    aliases = {
        "open": "open",
        "submitted": "open",
        "pending": "open",
        "partially_filled": "partially_filled",
        "partial": "partially_filled",
        "filled": "filled",
        "done": "filled" if _to_decimal(filled_base, "0") > ZERO else "cancelled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
    }
    return aliases.get(status, status)


def _open_d3_exit_orders(
    orders: Iterable[Dict[str, Any]],
    *,
    ticker: str,
    linked_position_id: str,
) -> List[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    selected_position = str(linked_position_id or "").strip()
    out: List[Dict[str, Any]] = []
    for order in orders:
        if _normalize_ticker(order.get("ticker")) != selected_ticker:
            continue
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if str(order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
            continue
        if str(order.get("status") or "").strip().lower() not in {"planned", "pending", "submitted", "open", "partially_filled", "cancel_pending", "replace_pending"}:
            continue
        if selected_position and str(order.get("linked_position_id") or "").strip() != selected_position:
            continue
        out.append(dict(order))
    return out


def _default_outline(*, current_exchange_order_id: str, replacement_price: str, replacement_size: str) -> List[Dict[str, Any]]:
    return [
        {
            "step": 1,
            "name": "cancel_existing_order",
            "dry_run_only": True,
            "live_allowed_now": False,
            "order_id": current_exchange_order_id,
            "requires_future_ack": True,
        },
        {
            "step": 2,
            "name": "wait_for_confirmed_cancel",
            "dry_run_only": True,
            "live_allowed_now": False,
            "required_evidence": "confirmed_cancelled_or_terminal_closeout_before_replace",
            "fail_closed_on_uncertain_cancel": True,
        },
        {
            "step": 3,
            "name": "submit_replacement_after_confirmed_cancel",
            "dry_run_only": True,
            "live_allowed_now": False,
            "side": "SELL",
            "replacement_price": replacement_price,
            "replacement_size_base": replacement_size,
            "post_only": True,
            "requires_confirmed_cancel": True,
            "requires_future_ack": True,
        },
    ]


def build_phase_d4_cancel_replace_plan(
    *,
    preview_report: Dict[str, Any],
    current_order: Optional[Dict[str, Any]] = None,
    linked_position_id: str = "",
    position: Optional[Dict[str, Any]] = None,
    product_rules: Optional[Dict[str, Any]] = None,
    open_orders: Optional[Iterable[Dict[str, Any]]] = None,
    fake_order_status_snapshot: Optional[Dict[str, Any]] = None,
    operator_mode: str = "dry_run_only",
    coinbase_client: Any = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now_dt = now or _now()
    preview = dict(preview_report or {})
    order = dict(current_order or {})
    position = dict(position or {})
    rules = dict(product_rules or {})
    orders = list(open_orders or ([order] if order else []))
    fake_status = dict(fake_order_status_snapshot or {})
    selected_ticker = _normalize_ticker(preview.get("ticker") or order.get("ticker"))
    selected_position = str(linked_position_id or preview.get("linked_position_id") or order.get("linked_position_id") or "").strip()
    client_order_id = str(order.get("client_order_id") or preview.get("client_order_id") or preview.get("current_order_id") or "").strip()
    exchange_order_id = str(order.get("exchange_order_id") or order.get("order_id") or preview.get("exchange_order_id") or "").strip()
    current_price = _to_decimal(order.get("limit_price") or preview.get("current_exit_price"), "0")
    replacement_price = _to_decimal(preview.get("proposed_replacement_price"), "0")
    replacement_size = _to_decimal(order.get("remaining_size") or order.get("size_base"), "0")
    filled_base = _to_decimal(order.get("filled_base") or order.get("filled_size"), "0")
    fill_count = _to_int(order.get("fill_count"), 0)
    reserved_base = _to_decimal(position.get("reserved_base_open_exit_orders"), "0")
    min_order_quote = _to_decimal(rules.get("min_order_quote"), "0")
    estimated_quote = replacement_price * replacement_size if replacement_price > ZERO and replacement_size > ZERO else ZERO
    preview_action = str(preview.get("proposed_action") or "").strip()
    preview_status = str(preview.get("status") or "").strip()
    preview_post_only = bool(preview.get("post_only_feasible", True))
    duplicate_orders = _open_d3_exit_orders(orders, ticker=selected_ticker, linked_position_id=selected_position)

    blockers: List[str] = []
    warnings: List[str] = []

    if coinbase_client is not None:
        warnings.append("coinbase_client_ignored_dry_run_only")
    if operator_mode not in {"dry_run_only", "future_ack_required"}:
        blockers.append("operator_mode_invalid")
    if not order:
        blockers.append("open_d3_exit_order_not_found")
    if len(duplicate_orders) > 1:
        blockers.append("duplicate_open_d3_exit_orders_for_position")
    if filled_base > ZERO or fill_count > 0:
        blockers.append("current_order_has_fills_route_to_d3_lifecycle_first")
    if replacement_size <= ZERO:
        blockers.append("replacement_size_missing")
    if reserved_base < replacement_size:
        blockers.append("reserved_base_less_than_replacement_size")
    if replacement_price > ZERO and min_order_quote > ZERO and estimated_quote < min_order_quote:
        blockers.append("replacement_below_min_order_quote")
    if preview_action == "preview_reprice_candidate" and not preview_post_only:
        blockers.append("replacement_post_only_unsafe")
    if "candidate_crosses_book_post_only_unsafe" in set(preview.get("blockers") or []):
        blockers.append("replacement_post_only_unsafe")

    fake_status_value = ""
    if fake_status:
        fake_status_value = _normalize_order_status(
            fake_status.get("normalized_status") or fake_status.get("status") or fake_status.get("raw_status"),
            filled_base=fake_status.get("filled_base", "0"),
        )
        if fake_status_value in {"cancelled", "expired", "rejected"}:
            blockers.append("fake_order_status_terminal_route_to_d3_terminal_closeout")
        elif fake_status_value in {"partially_filled", "filled"}:
            blockers.append("fake_order_status_fill_route_to_d3_lifecycle")
        elif fake_status_value not in {"", "open"}:
            blockers.append("fake_order_status_not_open")

    if preview_action != "preview_reprice_candidate":
        proposed_action = "no_op_keep_open" if not blockers and preview_action == "keep_open" else "blocked"
        status = "d4_cancel_replace_plan_noop_keep_open" if proposed_action == "no_op_keep_open" else "d4_cancel_replace_plan_blocked"
        reason = "preview_not_reprice_candidate"
        if blockers:
            reason = blockers[0]
        return _json_safe({
            "generated_at": now_dt.isoformat(),
            "phase": D4_CANCEL_REPLACE_PLANNER_PHASE,
            "status": status,
            "proposed_action": proposed_action,
            "reason": reason,
            "ticker": selected_ticker,
            "linked_position_id": selected_position,
            "current_order_id": client_order_id,
            "current_exchange_order_id": exchange_order_id,
            "current_price": str(current_price),
            "replacement_price": "",
            "replacement_size_base": str(replacement_size),
            "estimated_quote": "0",
            "cancel_first_required": True,
            "replace_only_after_confirmed_cancel": True,
            "live_cancel_allowed": False,
            "live_replace_allowed": False,
            "no_coinbase_call": True,
            "no_live_action": True,
            "state_write_performed": False,
            "required_future_ack": "",
            "requires_future_ack": False,
            "blockers": blockers,
            "warnings": warnings,
            "future_execution_outline": [],
            "preview_status": preview_status,
            "preview_proposed_action": preview_action,
            "fake_order_status": fake_status_value,
        })

    if replacement_price <= ZERO:
        blockers.append("replacement_price_missing")

    status = "d4_cancel_replace_plan_blocked" if blockers else "d4_cancel_replace_plan_ready"
    proposed_action = "blocked" if blockers else "dry_run_cancel_replace_plan_ready"
    reason = blockers[0] if blockers else "preview_candidate_ready_cancel_first_plan_only"
    outline = [] if blockers else _default_outline(
        current_exchange_order_id=exchange_order_id,
        replacement_price=str(replacement_price),
        replacement_size=str(replacement_size),
    )
    return _json_safe({
        "generated_at": now_dt.isoformat(),
        "phase": D4_CANCEL_REPLACE_PLANNER_PHASE,
        "status": status,
        "proposed_action": proposed_action,
        "reason": reason,
        "ticker": selected_ticker,
        "linked_position_id": selected_position,
        "current_order_id": client_order_id,
        "current_exchange_order_id": exchange_order_id,
        "current_price": str(current_price),
        "replacement_price": str(replacement_price),
        "replacement_size_base": str(replacement_size),
        "estimated_quote": str(estimated_quote),
        "cancel_first_required": True,
        "replace_only_after_confirmed_cancel": True,
        "live_cancel_allowed": False,
        "live_replace_allowed": False,
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "required_future_ack": D4_CANCEL_REPLACE_REQUIRED_ACK if not blockers else "",
        "requires_future_ack": not bool(blockers),
        "blockers": blockers,
        "warnings": warnings,
        "future_execution_outline": outline,
        "preview_status": preview_status,
        "preview_proposed_action": preview_action,
        "fake_order_status": fake_status_value,
        "cancel_uncertainty_policy": "fail_closed_no_replace_without_confirmed_cancel",
    })


__all__ = [
    "D4_CANCEL_REPLACE_PLANNER_PHASE",
    "D4_CANCEL_REPLACE_REQUIRED_ACK",
    "build_phase_d4_cancel_replace_plan",
]
