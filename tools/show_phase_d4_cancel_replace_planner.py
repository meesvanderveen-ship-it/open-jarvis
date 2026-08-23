#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d4_cancel_replace_planner import build_phase_d4_cancel_replace_plan


def _load_json(path: str | Path) -> Dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_orders(path: str | Path) -> List[Dict[str, Any]]:
    payload = _load_json(path)
    orders = payload.get("orders")
    if isinstance(orders, dict):
        return [dict(v) for v in orders.values() if isinstance(v, dict)]
    if isinstance(orders, list):
        return [dict(v) for v in orders if isinstance(v, dict)]
    return []


def _find_order(orders: Iterable[Dict[str, Any]], *, client_order_id: str, exchange_order_id: str) -> Dict[str, Any]:
    for order in orders:
        if client_order_id and str(order.get("client_order_id") or "").strip() == client_order_id:
            return dict(order)
        order_exchange = str(order.get("exchange_order_id") or order.get("order_id") or "").strip()
        if exchange_order_id and order_exchange == exchange_order_id:
            return dict(order)
    return {}


def _find_position(path: str | Path, *, ticker: str) -> Dict[str, Any]:
    payload = _load_json(path)
    positions = payload.get("positions")
    if isinstance(positions, dict):
        position = positions.get(ticker)
        if isinstance(position, dict):
            return dict(position)
    position = payload.get(ticker)
    if isinstance(position, dict):
        return dict(position)
    return {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Offline D.4 cancel/replace dry-run planner. No Coinbase calls, no live action.")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--client-order-id", required=True)
    parser.add_argument("--exchange-order-id", required=True)
    parser.add_argument("--linked-position-id", required=True)
    parser.add_argument("--orders-file", default="state/open_orders.json")
    parser.add_argument("--positions-file", default="state/positions.json")
    parser.add_argument("--preview-fixture", required=True)
    parser.add_argument("--product-rules-fixture", required=True)
    parser.add_argument("--fake-order-status-fixture", default="")
    parser.add_argument("--operator-mode", default="dry_run_only", choices=["dry_run_only", "future_ack_required"])
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    orders = _load_orders(args.orders_file)
    return build_phase_d4_cancel_replace_plan(
        preview_report=_load_json(args.preview_fixture),
        current_order=_find_order(
            orders,
            client_order_id=args.client_order_id,
            exchange_order_id=args.exchange_order_id,
        ),
        linked_position_id=args.linked_position_id,
        position=_find_position(args.positions_file, ticker=args.ticker),
        product_rules=_load_json(args.product_rules_fixture),
        open_orders=orders,
        fake_order_status_snapshot=_load_json(args.fake_order_status_fixture) if args.fake_order_status_fixture else None,
        operator_mode=args.operator_mode,
        now=datetime.now(timezone.utc),
    )


def main() -> int:
    args = parse_args()
    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
