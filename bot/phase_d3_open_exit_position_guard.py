from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from bot.order_store import OrderStore


ZERO = Decimal("0")
D3_OPEN_EXIT_POSITION_GUARD_PHASE = "D3_open_exit_position_guard_v2"
D3_OPEN_EXIT_POSITION_GUARD_VERSION = "v2"
D3_GUARD_OPEN_ORDER_STATUSES = {"submitted", "open", "partially_filled", "cancel_pending", "replace_pending"}
D3_GUARD_ALLOWED_EVIDENCE_STATUSES = {"filled", "cancelled", "expired", "rejected"}


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


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def logical_position_id_candidates(
    position: Optional[Dict[str, Any]] = None,
    *,
    linked_position_id: str = "",
) -> List[str]:
    row = _as_dict(position)
    candidates: List[str] = []
    for value in (
        linked_position_id,
        row.get("linked_position_id"),
        row.get("recovery_linked_position_id"),
        row.get("phase_c43_exchange_order_id"),
        row.get("position_id"),
        row.get("order_id"),
        row.get("source_order_id"),
        row.get("source_client_order_id"),
        row.get("phase_c43_client_order_id"),
    ):
        text = str(value or "").strip()
        if text and text not in candidates:
            candidates.append(text)
    return candidates


def _order_reference_candidates(order: Dict[str, Any]) -> Dict[str, List[str]]:
    return {
        "linked_position_id": [str(order.get("linked_position_id") or "").strip()],
        "recovery_linked_position_id": [str(order.get("recovery_linked_position_id") or "").strip()],
        "phase_c43_exchange_order_id": [str(order.get("phase_c43_exchange_order_id") or "").strip()],
        "order_id": [
            str(order.get("order_id") or "").strip(),
            str(order.get("exchange_order_id") or "").strip(),
        ],
        "source_order_id": [str(order.get("source_order_id") or "").strip()],
        "source_client_order_id": [str(order.get("source_client_order_id") or "").strip()],
        "replacement_of_client_order_id": [str(order.get("replacement_of_client_order_id") or "").strip()],
        "replacement_of_exchange_order_id": [str(order.get("replacement_of_exchange_order_id") or "").strip()],
        "client_order_id": [str(order.get("client_order_id") or "").strip()],
    }


def _flatten_nonempty(values: Dict[str, List[str]]) -> List[str]:
    flattened: List[str] = []
    for items in values.values():
        for item in items:
            if item and item not in flattened:
                flattened.append(item)
    return flattened


def _single_ticker_fallback_match(
    *,
    store: OrderStore,
    ticker: str,
    current_order: Dict[str, Any],
) -> bool:
    matches: List[Dict[str, Any]] = []
    for order in store.open_exit_orders(ticker=ticker or None):
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if str(order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
            continue
        if str(order.get("status") or "").strip().lower() not in D3_GUARD_OPEN_ORDER_STATUSES:
            continue
        if _to_decimal(order.get("remaining_size") or order.get("size_base"), "0") <= ZERO:
            continue
        matches.append(dict(order))
    if len(matches) != 1:
        return False
    only_match = matches[0]
    only_id = str(only_match.get("client_order_id") or only_match.get("exchange_order_id") or only_match.get("order_id") or "").strip()
    current_id = str(current_order.get("client_order_id") or current_order.get("exchange_order_id") or current_order.get("order_id") or "").strip()
    return bool(only_id and current_id and only_id == current_id)


def match_open_d3_exit_order_to_position(
    order: Dict[str, Any],
    *,
    ticker: str,
    position: Optional[Dict[str, Any]] = None,
    linked_position_id: str = "",
    order_store: Optional[OrderStore] = None,
) -> Dict[str, Any]:
    row = _as_dict(position)
    selected_ticker = _normalize_ticker(ticker or row.get("ticker"))
    position_candidates = logical_position_id_candidates(row, linked_position_id=linked_position_id)
    order_candidates = _order_reference_candidates(order)
    candidate_set = set(position_candidates)
    matched_values: List[str] = []
    matched_strategies: List[str] = []

    for strategy, values in order_candidates.items():
        clean_values = [value for value in values if value]
        if not clean_values:
            continue
        overlap = [value for value in clean_values if value in candidate_set]
        if overlap:
            matched_strategies.append(strategy)
            for value in overlap:
                if value not in matched_values:
                    matched_values.append(value)

    if matched_strategies:
        return {
            "matched": True,
            "match_strategy": "+".join(matched_strategies),
            "matched_values": matched_values,
            "position_candidates": position_candidates,
            "order_reference_candidates": _flatten_nonempty(order_candidates),
        }

    if selected_ticker and not position_candidates and order_store is not None and _single_ticker_fallback_match(
        store=order_store,
        ticker=selected_ticker,
        current_order=order,
    ):
        return {
            "matched": True,
            "match_strategy": "ticker_single_open_sell_fallback",
            "matched_values": [selected_ticker],
            "position_candidates": position_candidates,
            "order_reference_candidates": _flatten_nonempty(order_candidates),
        }

    return {
        "matched": False,
        "match_strategy": "",
        "matched_values": [],
        "position_candidates": position_candidates,
        "order_reference_candidates": _flatten_nonempty(order_candidates),
    }


def order_matches_logical_position(
    order: Dict[str, Any],
    *,
    ticker: str = "",
    position: Optional[Dict[str, Any]] = None,
    linked_position_id: str = "",
    order_store: Optional[OrderStore] = None,
) -> bool:
    return bool(
        match_open_d3_exit_order_to_position(
            order,
            ticker=ticker,
            position=position,
            linked_position_id=linked_position_id,
            order_store=order_store,
        ).get("matched")
    )


def find_open_d3_exit_reservations_for_position(
    *,
    ticker: str,
    position: Optional[Dict[str, Any]] = None,
    linked_position_id: str = "",
    order_store: Optional[OrderStore] = None,
) -> List[Dict[str, Any]]:
    store = order_store or OrderStore()
    selected_ticker = _normalize_ticker(ticker)
    matches: List[Dict[str, Any]] = []
    for order in store.open_exit_orders(ticker=selected_ticker or None):
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if str(order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
            continue
        if str(order.get("status") or "").strip().lower() not in D3_GUARD_OPEN_ORDER_STATUSES:
            continue
        if _to_decimal(order.get("remaining_size") or order.get("size_base"), "0") <= ZERO:
            continue
        match = match_open_d3_exit_order_to_position(
            order,
            ticker=selected_ticker,
            position=position,
            linked_position_id=linked_position_id,
            order_store=store,
        )
        if not match.get("matched"):
            continue
        enriched = dict(order)
        enriched["guard_match_strategy"] = str(match.get("match_strategy") or "")
        enriched["guard_matched_values"] = list(match.get("matched_values") or [])
        matches.append(enriched)
    return matches


def build_open_d3_exit_position_guard_report(
    *,
    ticker: str,
    current_position: Optional[Dict[str, Any]] = None,
    proposed_position: Optional[Dict[str, Any]] = None,
    linked_position_id: str = "",
    caller_reason: str = "",
    evidence_status: str = "",
    order_store: Optional[OrderStore] = None,
) -> Dict[str, Any]:
    current = _as_dict(current_position)
    proposed = _as_dict(proposed_position)
    selected_ticker = _normalize_ticker(ticker or current.get("ticker") or proposed.get("ticker"))
    matches = find_open_d3_exit_reservations_for_position(
        ticker=selected_ticker,
        position=proposed or current,
        linked_position_id=linked_position_id,
        order_store=order_store,
    )
    attempted_new_status = str(proposed.get("status") or current.get("status") or "").strip().lower()
    attempted_new_position_size_base = _to_decimal(
        proposed.get("position_size_base", current.get("position_size_base", "0")),
        "0",
    )
    attempted_new_bot_managed_base = _to_decimal(
        proposed.get("bot_managed_base", current.get("bot_managed_base", "0")),
        "0",
    )
    attempted_closed_at = (
        proposed.get("closed_at")
        or proposed.get("close_time")
        or proposed.get("synthetic_closed_at")
    )
    attempted_close = (
        attempted_new_status == "closed"
        or attempted_new_position_size_base <= ZERO
        or attempted_new_bot_managed_base <= ZERO
        or attempted_closed_at not in {None, ""}
    )
    selected_linked = linked_position_id or next(
        (candidate for candidate in logical_position_id_candidates(proposed or current) if candidate),
        "",
    )
    total_reserved_open_exit_base = sum(
        (_to_decimal(order.get("remaining_size") or order.get("size_base"), "0") for order in matches),
        ZERO,
    )
    normalized_evidence_status = str(evidence_status or "").strip().lower()
    allowed_if_reason = ""
    blockers: List[str] = []
    warnings: List[str] = []
    should_block = False

    if matches and attempted_close:
        evidence_hash = str(proposed.get("last_d3_reconcile_evidence_hash") or current.get("last_d3_reconcile_evidence_hash") or "")
        if caller_reason == "controlled_d3_lifecycle_apply" and normalized_evidence_status in D3_GUARD_ALLOWED_EVIDENCE_STATUSES and evidence_hash is not None:
            allowed_if_reason = "controlled_d3_lifecycle_apply_with_terminal_or_fill_evidence"
        else:
            should_block = True
            blockers.append("open_d3_exit_reservation_prevents_position_close")

    guard_status = "guard_no_open_d3_exit"
    reason = "no_open_d3_exit_reservation"
    if matches and attempted_close:
        if should_block:
            guard_status = "guard_blocked_open_d3_exit_reservation"
            reason = "open_d3_exit_reservation_prevents_position_close"
        else:
            guard_status = "guard_allowed_controlled_d3_lifecycle_apply"
            reason = allowed_if_reason
    elif matches:
        guard_status = "guard_open_d3_exit_present_no_close_attempt"
        reason = "open_d3_exit_present_but_no_close_attempt"

    match_strategies: List[str] = []
    matching_order_ids: List[str] = []
    for order in matches:
        strategy = str(order.get("guard_match_strategy") or "")
        if strategy and strategy not in match_strategies:
            match_strategies.append(strategy)
        for candidate in (
            str(order.get("client_order_id") or "").strip(),
            str(order.get("exchange_order_id") or order.get("order_id") or "").strip(),
        ):
            if candidate and candidate not in matching_order_ids:
                matching_order_ids.append(candidate)

    return _json_safe({
        "phase": D3_OPEN_EXIT_POSITION_GUARD_PHASE,
        "guard_version": D3_OPEN_EXIT_POSITION_GUARD_VERSION,
        "generated_at": _now_iso(),
        "guard_status": guard_status,
        "should_block_close": should_block,
        "reason": reason,
        "ticker": selected_ticker,
        "linked_position_id": selected_linked,
        "matching_open_d3_exit_count": len(matches),
        "matching_open_d3_exit_client_order_ids": [str(o.get("client_order_id") or "") for o in matches],
        "matching_open_d3_exit_exchange_order_ids": [
            str(o.get("exchange_order_id") or o.get("order_id") or "") for o in matches
        ],
        "last_guard_match_strategy": "|".join(match_strategies),
        "last_guard_matching_order_ids": matching_order_ids,
        "total_reserved_open_exit_base": str(total_reserved_open_exit_base),
        "attempted_new_status": attempted_new_status,
        "attempted_new_position_size_base": str(attempted_new_position_size_base),
        "attempted_new_bot_managed_base": str(attempted_new_bot_managed_base),
        "caller_reason": str(caller_reason or ""),
        "evidence_status": normalized_evidence_status,
        "allowed_if_reason": allowed_if_reason,
        "blockers": blockers,
        "warnings": warnings,
    })


def should_block_position_close_due_to_open_d3_exit(
    *,
    ticker: str,
    current_position: Optional[Dict[str, Any]] = None,
    proposed_position: Optional[Dict[str, Any]] = None,
    linked_position_id: str = "",
    caller_reason: str = "",
    evidence_status: str = "",
    order_store: Optional[OrderStore] = None,
) -> bool:
    report = build_open_d3_exit_position_guard_report(
        ticker=ticker,
        current_position=current_position,
        proposed_position=proposed_position,
        linked_position_id=linked_position_id,
        caller_reason=caller_reason,
        evidence_status=evidence_status,
        order_store=order_store,
    )
    return bool(report.get("should_block_close"))


__all__ = [
    "D3_OPEN_EXIT_POSITION_GUARD_PHASE",
    "D3_OPEN_EXIT_POSITION_GUARD_VERSION",
    "build_open_d3_exit_position_guard_report",
    "find_open_d3_exit_reservations_for_position",
    "logical_position_id_candidates",
    "match_open_d3_exit_order_to_position",
    "should_block_position_close_due_to_open_d3_exit",
]
