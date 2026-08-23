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
from bot.phase_c43_one_entry_smoke_test import extract_product_rules
from bot.phase_c43_controlled_entry_pilot import build_controlled_entry_pilot_report
from bot.state_store import StateStore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Controlled C.4.3 entry-only pilot runner around the existing smoke submitter")
    p.add_argument("--ticker", required=True, help="Bijv. BTC-USDC")
    p.add_argument("--quote-size", default="10.00", help="USDC quote-size; hard capped at 25 by guards")
    p.add_argument("--limit-price", required=True, help="Expliciete post-only limit price; geen market orders")
    p.add_argument("--submit-live", action="store_true", help="Plaats exact één live BUY als alle guards en ACKs groen zijn")
    p.add_argument("--one-shot-actual-entry-submit", action="store_true", help="Arms only this runner process for one exact C.4.3 live BUY without .env mutation")
    p.add_argument("--one-shot-arm-ack", default="", help="Exacte extra ACK vereist voor process-local one-shot arming")
    p.add_argument("--c43-human-go-ack", default="", help="Exacte C.4.3 smoke ACK vereist voor live")
    p.add_argument("--d31-human-ack", default="", help="Exacte D3.1 entry-only arming ACK vereist voor live")
    p.add_argument("--simulate-actual-submit-for-preview", action="store_true", help="Alleen preview: simuleert actual submit true zonder .env te wijzigen")
    p.add_argument("--skip-product-rules-fetch", action="store_true", help="Alleen voor offline diagnose/tests; niet gebruiken voor normale live submit")
    p.add_argument("--order-store", default="state/open_orders.json")
    p.add_argument("--order-events", default="logs/order_events.jsonl")
    p.add_argument("--audit-path", default="logs/phase_c_live_submit.jsonl")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = BotConfig()
    cfg.validate()

    client = CoinbaseClient() if args.submit_live else None
    product_rules = None
    if client is not None and not args.skip_product_rules_fetch:
        product_rules = extract_product_rules(client.get_product(args.ticker))

    report = build_controlled_entry_pilot_report(
        cfg=cfg,
        ticker=args.ticker,
        quote_size=Decimal(str(args.quote_size)),
        limit_price=Decimal(str(args.limit_price)),
        submit_live=bool(args.submit_live),
        one_shot_actual_entry_submit=bool(args.one_shot_actual_entry_submit),
        one_shot_arm_ack=args.one_shot_arm_ack,
        c43_human_ack=args.c43_human_go_ack,
        d31_human_ack=args.d31_human_ack,
        order_store=OrderStore(path=args.order_store, log_path=args.order_events),
        state_store=StateStore(),
        coinbase_client=client,
        product_rules=product_rules,
        audit_path=args.audit_path,
        simulate_actual_submit_for_preview=bool(args.simulate_actual_submit_for_preview),
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print("C.4.4.3 controlled C.4.3 entry-only pilot")
        print("================================================")
        print("status:", report.get("status"))
        print("ticker:", report.get("ticker"))
        print("quote_size:", report.get("quote_size"))
        print("limit_price:", report.get("limit_price"))
        print("submit_live:", report.get("submit_live"))
        print("live_order_submitted:", report.get("live_order_submitted"))
        print("blockers:", report.get("blockers"))
        print("warnings:", report.get("warnings"))
        print("one_shot_actual_entry_submit_armed_process_local:", report.get("one_shot_actual_entry_submit_armed_process_local"))
        print("one_shot_actual_entry_submit_blockers:", report.get("one_shot_actual_entry_submit_blockers"))
        print("open_before:", (report.get("counts_before") or {}).get("total_open_live_entry_orders"))
        print("open_after:", (report.get("counts_after") or {}).get("total_open_live_entry_orders"))
        print("C43 ACK required:", (report.get("ack_tokens") or {}).get("c43_human_ack_required"))
        print("D31 ACK required:", (report.get("ack_tokens") or {}).get("d31_human_ack_required"))
        print("Next steps:")
        for step in report.get("next_steps") or []:
            print("-", step)

    if report.get("status") == "controlled_entry_blocked":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
