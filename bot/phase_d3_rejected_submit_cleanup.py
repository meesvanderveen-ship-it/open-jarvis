from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from bot.order_store import OrderStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _has_reject_evidence(order: Dict[str, Any]) -> bool:
    response = order.get("coinbase_response") if isinstance(order.get("coinbase_response"), dict) else {}
    error_response = response.get("error_response") if isinstance(response.get("error_response"), dict) else {}
    if response.get("success") is False:
        return True
    if str(error_response.get("error") or "").strip().upper() == "INVALID_PRICE_PRECISION":
        return True
    if "invalid_price_precision" in str(order.get("reject_reason") or "").strip().lower():
        return True
    if "invalid_price_precision" in str(order.get("preview_failure_reason") or "").strip().lower():
        return True
    return False


def build_phase_d3_rejected_submit_cleanup_report(
    *,
    ticker: str,
    client_order_id: str,
    linked_position_id: str,
    reason: str,
    order_store: Optional[OrderStore] = None,
    apply: bool = False,
) -> Dict[str, Any]:
    store = order_store or OrderStore()
    selected_ticker = _normalize_ticker(ticker)
    selected_client_order_id = str(client_order_id or "").strip()
    selected_position_id = str(linked_position_id or "").strip()
    requested_reason = str(reason or "").strip()
    blockers: list[str] = []
    warnings: list[str] = []

    order = store.get_order(selected_client_order_id)
    if not order:
        blockers.append("client_order_id_not_found")
        order = {}

    if order:
        if _normalize_ticker(order.get("ticker")) != selected_ticker:
            blockers.append("ticker_mismatch")
        if str(order.get("linked_position_id") or "").strip() != selected_position_id:
            blockers.append("linked_position_id_mismatch")
        if str(order.get("exchange_order_id") or order.get("order_id") or "").strip():
            blockers.append("exchange_order_id_present")
        if str(order.get("status") or "").strip().lower() not in {"submitted", "open", "pending", "active"}:
            blockers.append("order_status_not_open_like")
        if not _has_reject_evidence(order):
            blockers.append("reject_evidence_missing")
        if str(order.get("side") or "").strip().upper() != "SELL":
            blockers.append("side_not_sell")

    proposed_updates = {
        "status": "rejected",
        "remaining_size": "0",
        "remaining_quote": "0",
        "rejected_at": _now_iso(),
        "finalized_at": _now_iso(),
        "closed_at": _now_iso(),
        "reject_reason": requested_reason,
    }

    applied = False
    updated_order = None
    if apply and not blockers and order:
        updated_order = store.update_order(
            selected_client_order_id,
            proposed_updates,
            event_type="phase_d3_live_exit_order_marked_rejected",
        )
        applied = updated_order is not None
        if not applied:
            blockers.append("order_update_failed")

    status = "phase_d3_rejected_submit_cleanup_dry_run"
    if apply and not blockers and applied:
        status = "phase_d3_rejected_submit_cleanup_applied"
    elif apply and blockers:
        status = "phase_d3_rejected_submit_cleanup_blocked"

    return _json_safe({
        "phase": "D3_rejected_submit_cleanup",
        "status": status,
        "dry_run": not apply,
        "state_write_performed": bool(applied),
        "ticker": selected_ticker,
        "client_order_id": selected_client_order_id,
        "linked_position_id": selected_position_id,
        "reason": requested_reason,
        "matched_order_found": bool(order),
        "matched_order": order,
        "proposed_updates": proposed_updates,
        "updated_order": updated_order,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "safety_policy": {
            "no_coinbase_calls": True,
            "no_cancel_replace": True,
            "position_unchanged": True,
            "c43_entry_state_unchanged": True,
            "single_order_record_only": True,
        },
    })


__all__ = ["build_phase_d3_rejected_submit_cleanup_report"]
