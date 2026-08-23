#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.coinbase_client import CoinbaseClient
from bot.order_store import OrderStore
from bot.phase_c43_one_entry_smoke_test import (
    C43_ONE_ENTRY_SMOKE_ACK,
    extract_product_rules,
    run_c43_one_live_entry_smoke_test,
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Submit or preview exactly one C43 post-only live entry smoke-test order")
    p.add_argument("--ticker", required=True, help="Bijv. BTC-USDC")
    p.add_argument("--quote-size", default="10.00", help="USDC quote-size; hard capped by config/max 25")
    p.add_argument("--limit-price", required=True, help="Expliciete limietprijs. Geen market orders.")
    p.add_argument("--submit-live", action="store_true", help="Plaats echt live als alle guards groen zijn")
    p.add_argument("--human-go-ack", default="", help=f"Vereist exact: {C43_ONE_ENTRY_SMOKE_ACK}")
    p.add_argument("--json", action="store_true", help="Print volledig JSON rapport")
    p.add_argument("--order-store", default="state/open_orders.json")
    p.add_argument("--order-events", default="logs/order_events.jsonl")
    p.add_argument("--audit-path", default="logs/phase_c_live_submit.jsonl")
    p.add_argument("--skip-product-rules-fetch", action="store_true", help="Alleen voor offline diagnose/tests; niet aanbevolen voor live")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = BotConfig()
    cfg.validate()

    quote_size = Decimal(str(args.quote_size))
    limit_price = Decimal(str(args.limit_price))
    client = CoinbaseClient() if args.submit_live else None
    product_rules = None
    if client is not None and not args.skip_product_rules_fetch:
        product_rules = extract_product_rules(client.get_product(args.ticker))

    store = OrderStore(path=args.order_store, log_path=args.order_events)
    report = run_c43_one_live_entry_smoke_test(
        cfg=cfg,
        ticker=args.ticker,
        quote_size=quote_size,
        limit_price=limit_price,
        submit_live=bool(args.submit_live),
        human_ack=args.human_go_ack,
        coinbase_client=client,
        order_store=store,
        product_rules=product_rules,
        audit_path=args.audit_path,
    )

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print("Phase C43 one live entry smoke-test")
        print("====================================")
        print("status:", report.get("status"))
        print("ticker:", report.get("ticker"))
        print("submit_requested:", report.get("submit_requested"))
        print("live_submission_attempted:", report.get("live_submission_attempted"))
        print("live_order_submitted:", report.get("live_order_submitted"))
        pre = report.get("preflight") or {}
        print("preflight_accepted:", pre.get("accepted"))
        print("blockers:", pre.get("blockers"))
        print("warnings:", pre.get("warnings"))
        print("ack_required_for_live:", C43_ONE_ENTRY_SMOKE_ACK)

    return 0 if report.get("status") != "smoke_blocked" else 2


if __name__ == "__main__":
    raise SystemExit(main())
