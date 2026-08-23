#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.order_store import OrderStore


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def build_cancel_updates(*, reason: str, now: str) -> Dict[str, Any]:
    return {
        "status": "cancelled",
        "cancelled_at": now,
        "closed_at": now,
        "cancel_reason": reason,
        "manual_cancel_confirmed": True,
        "coinbase_cancel_confirmed_by_user": True,
        "remaining_size": "0",
        "remaining_quote": "0",
        "fill_reconciliation_note": "manual_cancel_confirmed_no_position_created",
        "position_created": False,
        "d2_plan_created": False,
        "live_exit_order_created": False,
    }


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Mark a Phase C.4.3 live entry order as cancelled in the local OrderStore. "
            "This does not call Coinbase and never creates positions, D.2 plans or exit orders."
        )
    )
    p.add_argument("--order-store", default="state/open_orders.json")
    p.add_argument("--order-events", default="logs/order_events.jsonl")
    p.add_argument("--client-order-id", required=True)
    p.add_argument("--exchange-order-id", default="")
    p.add_argument("--ticker", default="BTC-USDC")
    p.add_argument("--reason", default="manual_cancel_on_coinbase")
    p.add_argument(
        "--allow-filled-local-order",
        action="store_true",
        help="Allow overriding a locally filled order. Default refuses this to avoid hiding a fill.",
    )
    args = p.parse_args()

    store = OrderStore(path=args.order_store, log_path=args.order_events)
    order = store.get_order(args.client_order_id)
    if not order:
        print(json.dumps({
            "status": "not_found",
            "client_order_id": args.client_order_id,
            "order_store": args.order_store,
        }, indent=2, sort_keys=True))
        return 2

    current_status = str(order.get("status") or "").strip().lower()
    if current_status == "filled" and not args.allow_filled_local_order:
        print(json.dumps({
            "status": "refused_local_order_already_filled",
            "client_order_id": args.client_order_id,
            "order_store": args.order_store,
            "safety_policy": "do_not_convert_filled_orders_to_cancelled_without_explicit_override",
        }, indent=2, sort_keys=True))
        return 4

    if _as_bool(order.get("position_created")) or _as_bool(order.get("d2_plan_created")):
        print(json.dumps({
            "status": "refused_position_or_d2_plan_already_created",
            "client_order_id": args.client_order_id,
            "position_created": order.get("position_created"),
            "d2_plan_created": order.get("d2_plan_created"),
            "safety_policy": "manual_cancel_tool_is_for_unfilled_entry_orders_only",
        }, indent=2, sort_keys=True))
        return 5

    current_exchange_id = str(order.get("exchange_order_id") or order.get("order_id") or "").strip()
    if args.exchange_order_id and current_exchange_id and args.exchange_order_id != current_exchange_id:
        print(json.dumps({
            "status": "exchange_order_id_mismatch",
            "client_order_id": args.client_order_id,
            "expected_exchange_order_id": args.exchange_order_id,
            "found_exchange_order_id": current_exchange_id,
            "order_store": args.order_store,
        }, indent=2, sort_keys=True))
        return 3

    updates = build_cancel_updates(reason=args.reason, now=now_iso())
    updated = store.update_order(
        args.client_order_id,
        updates,
        event_type="phase_c43_live_entry_order_manually_cancelled",
    )

    print(json.dumps({
        "status": "local_order_marked_cancelled",
        "client_order_id": args.client_order_id,
        "exchange_order_id": args.exchange_order_id or current_exchange_id,
        "ticker": args.ticker,
        "order_store": args.order_store,
        "updated_status": (updated or {}).get("status"),
        "remaining_size": (updated or {}).get("remaining_size"),
        "remaining_quote": (updated or {}).get("remaining_quote"),
        "note": "Local lifecycle updated only. No Coinbase call, no position, no D2 plan, no exit order.",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
