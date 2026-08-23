#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.order_store import OrderStore


def _load_orders(path: Path) -> Dict[str, Dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        orders = data.get("orders") if isinstance(data, dict) else None
        if isinstance(orders, dict):
            return {str(k): dict(v) for k, v in orders.items() if isinstance(v, dict)}
    except Exception:
        pass
    return {}


def _find_record(path: Path, client_order_id: str) -> Optional[Dict[str, Any]]:
    orders = _load_orders(path)
    if client_order_id in orders:
        return dict(orders[client_order_id])
    for record in orders.values():
        if str(record.get("client_order_id") or "") == client_order_id:
            return dict(record)
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Repair/import one Phase C43 live entry order record into the canonical open-order store")
    p.add_argument("--client-order-id", required=True)
    p.add_argument("--exchange-order-id", required=True, help="Coinbase order_id from success_response.order_id")
    p.add_argument("--source-order-store", default="state/orders.json", help="Where the smoke-test may have written the record before the store-default fix")
    p.add_argument("--target-order-store", default="state/open_orders.json", help="Canonical C43/strategy order store")
    p.add_argument("--order-events", default="logs/order_events.jsonl")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    client_order_id = str(args.client_order_id).strip()
    exchange_order_id = str(args.exchange_order_id).strip()
    source_path = Path(args.source_order_store)
    target_path = Path(args.target_order_store)

    record = _find_record(source_path, client_order_id) or _find_record(target_path, client_order_id)
    if record is None:
        report = {
            "status": "not_found",
            "client_order_id": client_order_id,
            "searched": [str(source_path), str(target_path)],
            "hint": "Run this on the server where the smoke-test wrote its local_order_record, or pass the correct --source-order-store.",
        }
        print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else report)
        return 2

    record["client_order_id"] = client_order_id
    record["exchange_order_id"] = exchange_order_id
    record["order_id"] = exchange_order_id
    record.setdefault("status", "submitted")
    if str(record.get("status") or "").strip().lower() in {"", "unknown"}:
        record["status"] = "submitted"
    record["opened_via_phase_c43"] = True
    record["repair_note"] = "imported_or_updated_by_repair_phase_c43_live_order_record"

    store = OrderStore(path=target_path, log_path=args.order_events)
    repaired = store.upsert_order(record, event_type="phase_c43_live_entry_order_record_repaired")
    report = {
        "status": "repaired",
        "client_order_id": client_order_id,
        "exchange_order_id": exchange_order_id,
        "source_order_store": str(source_path),
        "target_order_store": str(target_path),
        "order": repaired,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
