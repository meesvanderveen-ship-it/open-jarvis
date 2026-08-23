#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.coinbase_client import CoinbaseClient
from bot.coinbase_order_snapshot import fetch_coinbase_order_snapshot
from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.phase_d3_live_exit_reconciliation import (
    D3_LIVE_EXIT_RECONCILE_ACK,
    reconcile_phase_d3_live_exit_order,
)
from bot.state_store import StateStore


def _find_local_order(
    store: OrderStore,
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
) -> Dict[str, Any]:
    selected_ticker = str(ticker or "").strip().upper().replace("/", "-")
    selected_client = str(client_order_id or "").strip()
    selected_exchange = str(exchange_order_id or "").strip()
    if selected_client:
        order = store.get_order(selected_client)
        if isinstance(order, dict):
            return order
    for order in store.all_orders():
        if selected_ticker and str(order.get("ticker") or "").strip().upper() != selected_ticker:
            continue
        if str(order.get("exchange_order_id") or order.get("order_id") or "").strip() == selected_exchange:
            return dict(order)
    return {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Governed D.3 live exit reconciliation dry-run/apply")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--client-order-id", required=True)
    parser.add_argument("--exchange-order-id", required=True)
    parser.add_argument("--linked-position-id", required=True)
    parser.add_argument("--snapshot-fixture", default="")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--apply-ack", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _load_snapshot_fixture(path: str) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _resolve_snapshot(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    snapshot_fixture: str,
) -> Dict[str, Any]:
    if snapshot_fixture:
        payload = _load_snapshot_fixture(snapshot_fixture)
        return {
            "coinbase_call_succeeded": bool(payload.get("coinbase_call_succeeded", True)),
            **payload,
        }

    store = OrderStore()
    local_order = _find_local_order(
        store,
        ticker=ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
    )
    snapshot = fetch_coinbase_order_snapshot(
        coinbase_client=CoinbaseClient(),
        order_id=exchange_order_id,
        local_order=local_order,
        include_fills=True,
    )
    fills_summary = snapshot.get("fills_summary") or {}
    return {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "raw_status": snapshot.get("raw_status") or snapshot.get("status") or "",
        "normalized_status": snapshot.get("normalized_status") or "",
        "filled_base": snapshot.get("filled_base") or "0",
        "filled_quote": snapshot.get("filled_quote") or "0",
        "remaining_size": str(local_order.get("remaining_size") or local_order.get("size_base") or "0"),
        "avg_fill_price": snapshot.get("avg_fill_price") or "0",
        "fill_count": int(fills_summary.get("fill_count") or 0),
        "fees": str(local_order.get("fees_paid") or "0"),
        "liquidity": [],
        "snapshot": snapshot,
    }


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = BotConfig()
    cfg.validate()
    snapshot = _resolve_snapshot(
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
        snapshot_fixture=args.snapshot_fixture,
    )
    return reconcile_phase_d3_live_exit_order(
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
        linked_position_id=args.linked_position_id,
        snapshot=snapshot,
        order_store=OrderStore(),
        state_store=StateStore(),
        apply=bool(args.apply),
        apply_ack=args.apply_ack,
    )


def main() -> int:
    args = parse_args()
    if args.apply and args.dry_run:
        raise SystemExit("--dry-run en --apply zijn wederzijds exclusief")
    if not args.apply:
        args.dry_run = True
    report = build_report(args)
    report["required_apply_ack"] = D3_LIVE_EXIT_RECONCILE_ACK
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
