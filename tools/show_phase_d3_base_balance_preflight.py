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
from bot.coinbase_client import CoinbaseClient
from bot.order_store import OrderStore
from bot.phase_d3_base_balance_preflight import build_phase_d3_base_balance_preflight_report
from bot.state_store import StateStore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Read-only Coinbase/base-balance preflight for D.3 controlled SELL review")
    p.add_argument("--ticker", default="BTC-USDC")
    p.add_argument("--position-id", required=True)
    p.add_argument("--requested-sell-base", required=True)
    p.add_argument("--order-store", default="state/open_orders.json")
    p.add_argument("--order-events", default="logs/order_events.jsonl")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = BotConfig()
    cfg.validate()
    report = build_phase_d3_base_balance_preflight_report(
        ticker=args.ticker,
        position_id=args.position_id,
        requested_sell_base=args.requested_sell_base,
        coinbase_client=CoinbaseClient(),
        state_store=StateStore(),
        order_store=OrderStore(path=args.order_store, log_path=args.order_events),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print("D.3 base-balance preflight")
        print("==========================")
        print("status:", report.get("status"))
        print("ticker:", report.get("ticker"))
        print("requested_position_id:", report.get("requested_position_id"))
        print("requested_sell_base:", report.get("requested_sell_base"))
        print("local_position_size_base:", report.get("local_position_size_base"))
        print("local_bot_managed_base:", report.get("local_bot_managed_base"))
        print("live_base_available:", report.get("live_base_available"))
        print("live_base_total:", report.get("live_base_total"))
        print("live_quote_available:", report.get("live_quote_available"))
        print("sufficient_live_base_for_requested_sell:", report.get("sufficient_live_base_for_requested_sell"))
        print("local_vs_live_base_coherent:", report.get("local_vs_live_base_coherent"))
        print("safety_margin_base:", report.get("safety_margin_base"))
        print("blockers:", report.get("blockers"))
        print("warnings:", report.get("warnings"))
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
