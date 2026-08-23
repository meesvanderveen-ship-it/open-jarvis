from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from bot.order_store import OrderStore
from bot.state_store import StateStore


TERMINAL_FILL_STATUSES = {"filled", "done", "completed"}
ZERO = Decimal("0")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        return Decimal(text or default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def validate_entry_fill_to_position_contract(
    *,
    local_order: Dict[str, Any],
    live_order_snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    """Validate D.1 entry fill evidence before local position registration."""
    local = local_order if isinstance(local_order, dict) else {}
    live = live_order_snapshot if isinstance(live_order_snapshot, dict) else {}
    blockers: list[str] = []
    status = str(live.get("status") or live.get("normalized_status") or "").strip().lower()
    filled_base = _to_decimal(
        live.get("filled_base") or live.get("filled_size") or live.get("size"),
        "0",
    )
    avg_price = _to_decimal(
        live.get("avg_fill_price") or live.get("average_filled_price") or live.get("limit_price"),
        "0",
    )
    exchange_order_id = str(
        live.get("exchange_order_id")
        or live.get("order_id")
        or local.get("exchange_order_id")
        or local.get("order_id")
        or ""
    ).strip()
    local_exchange = str(local.get("exchange_order_id") or local.get("order_id") or "").strip()
    if status not in TERMINAL_FILL_STATUSES:
        blockers.append("terminal_fill_status_required")
    if filled_base <= ZERO:
        blockers.append("filled_base_required")
    if avg_price <= ZERO:
        blockers.append("avg_entry_price_required")
    if not exchange_order_id:
        blockers.append("exchange_order_id_required")
    if local_exchange and exchange_order_id and local_exchange != exchange_order_id:
        blockers.append("exchange_order_id_mismatch")
    return {
        "accepted": not blockers,
        "blockers": blockers,
        "status": status,
        "filled_base": str(filled_base),
        "avg_entry_price": str(avg_price),
        "exchange_order_id": exchange_order_id,
        "state_write_allowed": not blockers,
        "state_write_performed": False,
        "coinbase_submit_attempted": False,
        "coinbase_cancel_attempted": False,
        "coinbase_replace_attempted": False,
    }


def reconcile_entry_fill_to_position(
    *,
    cfg: Any,
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    live_orders_snapshot: Optional[list[Dict[str, Any]]] = None,
    apply_local: bool = False,
) -> Dict[str, Any]:
    """D.1 compatibility wrapper around the C.4.3 fill reconciliation bridge.

    The wrapper makes the apply boundary explicit: without ``apply_local=True``
    no OrderStore/StateStore mutation is performed, so terminal evidence can be
    previewed without registering a position or changing the local order.
    """
    if not apply_local:
        store = order_store or OrderStore()
        snapshots = live_orders_snapshot or []
        actions: list[Dict[str, Any]] = []
        by_key: Dict[str, Dict[str, Any]] = {}
        for snapshot in snapshots:
            if not isinstance(snapshot, dict):
                continue
            for key in (
                snapshot.get("client_order_id"),
                snapshot.get("exchange_order_id"),
                snapshot.get("order_id"),
            ):
                text = str(key or "").strip()
                if text:
                    by_key[text] = snapshot
        for local in store.open_entry_orders():
            cid = str(local.get("client_order_id") or "").strip()
            oid = str(local.get("exchange_order_id") or local.get("order_id") or "").strip()
            snapshot = by_key.get(cid) or by_key.get(oid) or {}
            if not snapshot:
                actions.append({"client_order_id": cid, "ticker": local.get("ticker"), "action": "no_live_snapshot", "status": "skipped"})
                continue
            validation = validate_entry_fill_to_position_contract(local_order=local, live_order_snapshot=snapshot)
            actions.append(
                {
                    "client_order_id": cid,
                    "ticker": local.get("ticker"),
                    "action": "filled_to_position" if validation["accepted"] else "blocked_missing_terminal_fill_evidence",
                    "validation": validation,
                    "state_write_performed": False,
                    "order_write_performed": False,
                }
            )
        return {
            "phase": "D1_fill_to_position_contract",
            "status": "fill_to_position_preview_completed",
            "apply_local_requested": False,
            "local_live_entry_orders_seen": len(store.open_entry_orders()),
            "actions": actions,
            "state_write_possible_only_with_terminal_fill": True,
            "coinbase_call_attempted": False,
            "coinbase_submit_attempted": False,
            "coinbase_cancel_attempted": False,
            "coinbase_replace_attempted": False,
            "state_write_performed": False,
            "order_write_performed": False,
            "safety_policy": {
                "preview_does_not_mutate_order_store": True,
                "preview_does_not_mutate_position_store": True,
            },
        }
    # D1 remains a contract/validation surface. C.4.4 is the sole owner of
    # fill -> position local apply, so this legacy entrypoint cannot mutate
    # OrderStore or StateStore even when a caller passes apply_local=True.
    return {
        "phase": "D1_fill_to_position_contract",
        "status": "apply_local_blocked_requires_c44_lifecycle_orchestrator",
        "apply_local_requested": bool(apply_local),
        "local_live_entry_orders_seen": len(store.open_entry_orders()),
        "actions": [],
        "authority_blockers": ["c43_local_apply_owned_by_c44_lifecycle_orchestrator"],
        "state_write_possible_only_with_terminal_fill": True,
        "state_write_performed": False,
        "order_write_performed": False,
        "coinbase_call_attempted": False,
        "coinbase_submit_attempted": False,
        "coinbase_cancel_attempted": False,
        "coinbase_replace_attempted": False,
        "safety_policy": {
            "d1_is_preview_and_contract_only": True,
            "local_apply_owned_by_c44_lifecycle_orchestrator": True,
        },
    }


__all__ = [
    "TERMINAL_FILL_STATUSES",
    "reconcile_entry_fill_to_position",
    "validate_entry_fill_to_position_contract",
]
