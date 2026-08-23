#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.phase_c43_autonomous_entry_live import build_phase_c43_status_report


def main() -> int:
    parser = argparse.ArgumentParser(description="Show C.4.3 autonomous entry live + fill-to-position bridge status")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--order-store", default="state/open_orders.json")
    parser.add_argument("--order-events", default="logs/order_events.jsonl")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    store = OrderStore(path=args.order_store, log_path=args.order_events, max_orders=max(200, int(getattr(cfg, "order_store_max_records", 2000))))
    report = build_phase_c43_status_report(cfg=cfg, ticker=args.ticker, order_store=store)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    print("Phase-C C.4.3 autonomous entry live + fill-to-position bridge")
    print("===============================================================")
    print("ticker:", report.get("ticker"))
    config = report.get("config") or {}
    print("enable_phase_c43_autonomous_entry_submitter:", config.get("enable_phase_c43_autonomous_entry_submitter"))
    print("enable_autonomous_small_live_orderbook_mode:", config.get("enable_autonomous_small_live_orderbook_mode"))
    print("enable_phase_c_actual_coinbase_submit:", config.get("enable_phase_c_actual_coinbase_submit"))
    print("enable_live_entry_orders:", config.get("enable_live_entry_orders"))
    print("enable_live_exit_orders:", config.get("enable_live_exit_orders"))
    print("phase_c_allowed_tickers:", config.get("phase_c_allowed_tickers"))
    print("phase_c_max_order_quote:", config.get("phase_c_max_order_quote"))
    print("autonomous_max_order_quote:", config.get("autonomous_max_order_quote"))
    print("autonomous_max_open_orders:", config.get("autonomous_max_open_orders"))
    counts = report.get("local_live_entry_order_counts") or {}
    print("\nLocal live entry orders:", json.dumps({k:v for k,v in counts.items() if k != "orders"}, ensure_ascii=False))
    rec = report.get("fill_reconciliation_preview") or {}
    print("Fill reconciliation preview status:", rec.get("status"))
    print("local_live_entry_orders_seen:", rec.get("local_live_entry_orders_seen"))
    print("actions:", len(rec.get("actions") or []))
    print("errors:", len(rec.get("errors") or []))
    print("\nSafety: entry-only, max 25 USDC/order, max 4 open orders, live exits blijven uit, geen follower order-lifecycle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
