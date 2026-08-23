"""Read-only, current-state evidence for live startup decisions.

Historical audit reports remain useful diagnostics, but they cannot establish
whether an order is reserved, a position is open, or the runner lock is held.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from bot.order_lifecycle import is_open_order_status


STATE_POSITIONS = Path("state/positions.json")
STATE_OPEN_ORDERS = Path("state/open_orders.json")
RUNTIME_LOCK = Path("state/runtime_mutation.lock")
ACTIVE_POSITION_STATUSES = frozenset({"open", "active"})
FINAL_POSITION_STATUSES = frozenset({"closed", "cancelled", "canceled", "filled", "rejected", "expired"})


def _load_json_object(path: Path) -> Tuple[Dict[str, Any], str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, "missing"
    except Exception:
        return {}, "unreadable"
    return (payload, "available") if isinstance(payload, dict) else ({}, "invalid")


def _position_risk_incomplete(position: Dict[str, Any]) -> bool:
    stop = str(position.get("stop_price") or "").strip()
    invalidation = str(position.get("invalidation_price") or "").strip()
    return bool(
        position.get("position_risk_incomplete")
        or str(position.get("protective_stop_status") or "").strip().lower() == "position_risk_incomplete"
        or stop in {"", "0", "0.0", "0.00"}
        or invalidation in {"", "0", "0.0", "0.00"}
    )


def _runtime_lock_path(root: Path) -> Path:
    configured = str(os.getenv("RUN_TRADER_LOOP_LOCK_PATH") or "").strip()
    if configured:
        candidate = Path(configured)
        return candidate if candidate.is_absolute() else root / candidate
    return root / RUNTIME_LOCK


def _inspect_runtime_lock(path: Path) -> Dict[str, Any]:
    """Check whether the flock is held without creating, truncating, or removing it."""
    if not path.exists():
        return {"path": str(path), "status": "absent", "held": False, "verifiable": True}
    try:
        import fcntl

        with path.open("r", encoding="utf-8") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return {"path": str(path), "status": "held", "held": True, "verifiable": True}
            try:
                contents = handle.read().strip()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except Exception as exc:
        return {
            "path": str(path),
            "status": "unverifiable",
            "held": False,
            "verifiable": False,
            "error_type": type(exc).__name__,
        }
    return {
        "path": str(path),
        "status": "not_held",
        "held": False,
        "verifiable": True,
        "stale_contents_ignored": bool(contents),
    }


def build_pre_live_current_state(root: Path) -> Dict[str, Any]:
    """Build the canonical read-only startup snapshot from current local state."""
    root = Path(root)
    positions, positions_status = _load_json_object(root / STATE_POSITIONS)
    orders_state, orders_status = _load_json_object(root / STATE_OPEN_ORDERS)
    orders = orders_state.get("orders") if isinstance(orders_state.get("orders"), dict) else None

    active_positions: List[str] = []
    risk_incomplete: List[str] = []
    unrecognised_positions: List[str] = []
    if positions_status == "available":
        for raw_ticker, raw_position in positions.items():
            if not isinstance(raw_position, dict):
                unrecognised_positions.append(str(raw_ticker).strip().upper())
                continue
            ticker = str(raw_position.get("ticker") or raw_ticker).strip().upper()
            status = str(raw_position.get("status") or "").strip().lower()
            if status in ACTIVE_POSITION_STATUSES:
                active_positions.append(ticker)
                if _position_risk_incomplete(raw_position):
                    risk_incomplete.append(ticker)
            elif status not in FINAL_POSITION_STATUSES:
                unrecognised_positions.append(ticker)

    open_order_ids: List[str] = []
    if orders_status == "available" and orders is None:
        orders_status = "invalid"
    if isinstance(orders, dict):
        for raw_order_id, raw_order in orders.items():
            if not isinstance(raw_order, dict):
                continue
            if is_open_order_status(raw_order.get("status")):
                open_order_ids.append(str(raw_order.get("client_order_id") or raw_order_id).strip())

    lock = _inspect_runtime_lock(_runtime_lock_path(root))
    blockers: List[str] = []
    if positions_status != "available":
        blockers.append("current_positions_state_unavailable")
    if orders_status != "available":
        blockers.append("current_open_orders_state_unavailable")
    if unrecognised_positions:
        blockers.append("current_position_status_unverifiable")
    if risk_incomplete:
        blockers.append("risk_incomplete_positions")
    if lock.get("held"):
        blockers.append("runtime_mutation_lock_held")
    elif not lock.get("verifiable"):
        blockers.append("runtime_mutation_lock_unverifiable")

    return {
        "positions_state_status": positions_status,
        "orders_state_status": orders_status,
        "state_evidence_available": positions_status == "available" and orders_status == "available",
        "open_positions": sorted(set(active_positions)),
        "risk_incomplete_positions": sorted(set(risk_incomplete)),
        "unrecognised_position_tickers": sorted(set(unrecognised_positions)),
        "open_order_ids": sorted(set(open_order_ids)),
        "open_orders": len(open_order_ids),
        "runtime_lock": lock,
        "blockers": sorted(set(blockers)),
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "lock_removed": False,
    }


__all__ = ["build_pre_live_current_state"]
