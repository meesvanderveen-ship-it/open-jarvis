from __future__ import annotations

from typing import Any, Dict, Optional

from bot.order_store import FINAL_ORDER_STATUSES, OrderStore
from bot.phase_d3_open_exit_lifecycle_manager import (
    D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    build_phase_d3_open_exit_lifecycle_report,
)
from bot.state_store import StateStore


D3_CANCEL_CLOSEOUT_LOCAL_RECONCILE_ACK = (
    "I_UNDERSTAND_AND_APPROVE_D3_CANCEL_CLOSEOUT_LOCAL_RECONCILE"
)


def _cancelled_snapshot(*, evidence_hash: str) -> Dict[str, Any]:
    return {
        "coinbase_call_attempted": False,
        "coinbase_call_succeeded": True,
        "raw_status": "CANCELLED",
        "normalized_status": "cancelled",
        "filled_base": "0",
        "filled_quote": "0",
        "avg_fill_price": "0",
        "fill_count": 0,
        "remaining_size": "0.00006489",
        "fees": "0",
        "evidence_source": "coinbase_read_only_evidence",
        "evidence_hash_expected": str(evidence_hash or "").strip(),
    }


def _open_d3_exit_count(order_store: OrderStore, ticker: str) -> int:
    return sum(
        1
        for order in order_store.open_exit_orders(ticker=ticker)
        if str(order.get("phase") or "") == "D3_controlled_live_reduce_only_exits"
    )


def _matching_order(order_store: OrderStore, client_order_id: str) -> Dict[str, Any]:
    order = order_store.get_order(client_order_id)
    return dict(order) if isinstance(order, dict) else {}


def _decimal_text(value: Any, default: str = "0") -> str:
    from decimal import Decimal, InvalidOperation

    try:
        if value is None or str(value).strip() == "":
            return str(Decimal(default))
        return str(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return str(Decimal(default))


def _release_cancelled_reservation(
    *,
    state_store: StateStore,
    ticker: str,
    before_position: Dict[str, Any],
    reservation_before: str,
    client_order_id: str,
    exchange_order_id: str,
    evidence_hash: str,
) -> Dict[str, Any]:
    from decimal import Decimal

    current = state_store.get_position(ticker) or before_position or {}
    position_base = Decimal(_decimal_text(current.get("position_size_base"), "0"))
    bot_managed_base = Decimal(_decimal_text(current.get("bot_managed_base"), "0"))
    released_base = Decimal(_decimal_text(reservation_before, "0"))
    total_managed = max(bot_managed_base, position_base + released_base)
    return state_store.upsert_position(
        ticker,
        {
            "status": "open",
            "position_size_base": str(total_managed),
            "bot_managed_base": str(total_managed),
            "reserved_base_open_exit_orders": "0",
            "last_d3_cancel_closeout_client_order_id": client_order_id,
            "last_d3_cancel_closeout_exchange_order_id": exchange_order_id,
            "last_d3_cancel_closeout_evidence_hash": evidence_hash,
            "last_d3_cancel_closeout_action": "mark_cancelled_release_reservation",
        },
        caller_reason="controlled_d3_cancel_closeout_local_reconcile",
        evidence_status="cancelled",
    )


def build_phase_d3_cancel_closeout_local_reconcile_report(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    evidence_hash: str,
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    apply: bool = False,
    ack: str = "",
) -> Dict[str, Any]:
    store = order_store or OrderStore()
    states = state_store or StateStore()
    before_order = _matching_order(store, client_order_id)
    before_position = states.get_position(ticker) or {}
    open_count_before = _open_d3_exit_count(store, ticker)
    reservation_before = str((before_position or {}).get("reserved_base_open_exit_orders") or "0")
    local_order_status_before = str((before_order or {}).get("status") or "")
    local_position_status_before = str((before_position or {}).get("status") or "")

    report: Dict[str, Any] = {
        "phase": "D3_cancel_closeout_local_reconcile_v1",
        "mode": "apply" if apply else "preview",
        "ticker": ticker,
        "client_order_id": client_order_id,
        "exchange_order_id": exchange_order_id,
        "linked_position_id": linked_position_id,
        "evidence_hash": str(evidence_hash or "").strip(),
        "evidence_status": "cancelled",
        "fill_count": 0,
        "filled_base": "0",
        "local_order_status_before": local_order_status_before,
        "local_position_status_before": local_position_status_before,
        "open_d3_exit_count_before": open_count_before,
        "reservation_before": reservation_before,
        "proposed_order_status_after": "cancelled",
        "proposed_remaining_size_after": "0",
        "proposed_reserved_base_open_exit_orders_after": "0",
        "proposed_open_d3_exit_count_after": 0,
        "position_will_remain_open": True,
        "no_coinbase_call": True,
        "no_live_action": True,
        "coinbase_call_attempted": False,
        "live_action_performed": False,
        "state_write_performed": False,
        "ack_valid": not apply or str(ack or "").strip() == D3_CANCEL_CLOSEOUT_LOCAL_RECONCILE_ACK,
        "required_ack": D3_CANCEL_CLOSEOUT_LOCAL_RECONCILE_ACK,
        "blockers": [],
        "warnings": [],
    }

    if apply and not report["ack_valid"]:
        report["status"] = "d3_cancel_closeout_local_reconcile_blocked"
        report["blockers"].append("d3_cancel_closeout_local_reconcile_ack_required")
        return report
    if local_position_status_before.lower() != "open":
        report["blockers"].append("local_position_not_open")
    if local_order_status_before.lower() not in {"submitted", "open", "partially_filled", "cancel_pending"}:
        report["blockers"].append("local_order_not_open_or_submitted")
    if open_count_before != 1:
        report["blockers"].append("open_d3_exit_count_before_not_one")

    if report["blockers"]:
        report["status"] = "d3_cancel_closeout_local_reconcile_blocked"
        return report

    lifecycle_preview_report = build_phase_d3_open_exit_lifecycle_report(
        ticker=ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        linked_position_id=linked_position_id,
        order_store=store,
        state_store=states,
        snapshot=_cancelled_snapshot(evidence_hash=evidence_hash),
        allow_coinbase_poll=False,
        apply_local=False,
        apply_ack="",
    )
    lifecycle_report = lifecycle_preview_report
    actual_hash = str(lifecycle_preview_report.get("evidence_hash") or "")
    if str(evidence_hash or "").strip() and actual_hash != str(evidence_hash or "").strip():
        report["blockers"].append("evidence_hash_mismatch")

    lifecycle_blockers = list(lifecycle_preview_report.get("blockers") or [])
    if lifecycle_blockers:
        report["blockers"].extend(lifecycle_blockers)

    released_position: Dict[str, Any] = {}
    if apply and not report["blockers"]:
        lifecycle_report = build_phase_d3_open_exit_lifecycle_report(
            ticker=ticker,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            linked_position_id=linked_position_id,
            order_store=store,
            state_store=states,
            snapshot=_cancelled_snapshot(evidence_hash=evidence_hash),
            allow_coinbase_poll=False,
            apply_local=True,
            apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
        )
        lifecycle_blockers = list(lifecycle_report.get("blockers") or [])
        if lifecycle_blockers:
            report["blockers"].extend(lifecycle_blockers)

    if apply and not report["blockers"] and bool(lifecycle_report.get("state_write_performed")):
        released_position = _release_cancelled_reservation(
            state_store=states,
            ticker=ticker,
            before_position=before_position,
            reservation_before=reservation_before,
            client_order_id=client_order_id,
            exchange_order_id=exchange_order_id,
            evidence_hash=actual_hash or str(evidence_hash or "").strip(),
        )

    after_order = _matching_order(store, client_order_id)
    after_position = states.get_position(ticker) or {}
    open_count_after = _open_d3_exit_count(store, ticker)
    local_order_status_after = str((after_order or {}).get("status") or "")
    local_position_status_after = str((after_position or {}).get("status") or "")

    report.update(
        {
            "lifecycle_status": str(lifecycle_report.get("status") or ""),
            "lifecycle_proposed_action": str(lifecycle_report.get("proposed_action") or ""),
            "evidence_hash": actual_hash or report["evidence_hash"],
            "filled_base": str(lifecycle_report.get("filled_base") or "0"),
            "filled_quote": str(lifecycle_report.get("filled_quote") or "0"),
            "avg_fill_price": str(lifecycle_report.get("avg_fill_price") or "0"),
            "fill_count": int(lifecycle_report.get("fill_count") or 0),
            "remaining_size_before": str(before_order.get("remaining_size") or "0"),
            "remaining_size_after": str(after_order.get("remaining_size") or lifecycle_report.get("remaining_size") or "0"),
            "reservation_after": str((after_position or {}).get("reserved_base_open_exit_orders") or "0"),
            "open_d3_exit_count_after": open_count_after,
            "local_order_status_after": local_order_status_after,
            "local_position_status_after": local_position_status_after,
            "state_write_performed": bool(lifecycle_report.get("state_write_performed")),
            "coinbase_call_attempted": False,
            "live_action_performed": False,
            "no_coinbase_call": True,
            "no_live_action": True,
            "proposed_order_updates": dict(lifecycle_report.get("proposed_order_updates") or {}),
            "proposed_position_updates": {
                **dict(lifecycle_report.get("proposed_position_updates") or {}),
                **(
                    {
                        "position_size_base": str(after_position.get("position_size_base") or ""),
                        "bot_managed_base": str(after_position.get("bot_managed_base") or ""),
                        "reserved_base_open_exit_orders": str(after_position.get("reserved_base_open_exit_orders") or "0"),
                    }
                    if released_position
                    else {}
                ),
            },
            "warnings": list(lifecycle_report.get("warnings") or []),
        }
    )
    if report["blockers"]:
        report["status"] = "d3_cancel_closeout_local_reconcile_blocked"
        return report

    report["status"] = (
        "d3_cancel_closeout_local_reconcile_applied"
        if apply and report["state_write_performed"] and local_order_status_after.lower() in FINAL_ORDER_STATUSES
        else "d3_cancel_closeout_local_reconcile_preview_ready"
    )
    return report


__all__ = [
    "D3_CANCEL_CLOSEOUT_LOCAL_RECONCILE_ACK",
    "build_phase_d3_cancel_closeout_local_reconcile_report",
]
