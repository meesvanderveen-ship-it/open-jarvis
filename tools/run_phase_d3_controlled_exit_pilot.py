#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.coinbase_client import CoinbaseClient
from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.phase_c43_one_entry_smoke_test import extract_product_rules
from bot.phase_d3_controlled_exit_pilot import build_controlled_exit_pilot_report
from bot.state_store import StateStore


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Controlled D.3 TP1 reduce-only SELL pilot runner")
    p.add_argument("--ticker", default="BTC-USDC")
    p.add_argument("--submit-live", action="store_true")
    p.add_argument(
        "--use-live-exchange-rules-preview",
        action="store_true",
        help="Preview-only: haal Coinbase product rules read-only op zodat fingerprint/rounding exact de live-context volgt zonder submit",
    )
    p.add_argument("--one-shot-actual-exit-submit", action="store_true")
    p.add_argument("--one-shot-arm-ack", default="")
    p.add_argument("--d3-human-ack", default="")
    p.add_argument("--require-position-id", default="")
    p.add_argument("--require-plan-id", default="")
    p.add_argument("--require-plan-fingerprint", default="", help="Inhoudelijke D.2 plan-acceptatieguard; plan_id blijft alleen trace/debug")
    p.add_argument("--skip-product-rules-fetch", action="store_true")
    p.add_argument("--order-store", default="state/open_orders.json")
    p.add_argument("--order-events", default="logs/order_events.jsonl")
    p.add_argument("--audit-path", default="logs/phase_d3_controlled_live_exits.jsonl")
    p.add_argument("--json", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    cfg = BotConfig()
    cfg.validate()

    fetch_live_exchange_rules = bool(args.submit_live or args.use_live_exchange_rules_preview)
    client = CoinbaseClient() if args.submit_live else None
    exchange_rules = None
    exchange_rules_fetch_error = None
    exchange_rules_context = "default_preview_fallback"
    if fetch_live_exchange_rules and not args.skip_product_rules_fetch:
        try:
            exchange_rules = extract_product_rules(CoinbaseClient().get_product(args.ticker))
            exchange_rules_context = "coinbase_live_product_rules"
        except Exception as exc:
            exchange_rules_fetch_error = {
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            exchange_rules_context = "coinbase_live_product_rules_fetch_failed"

    report = build_controlled_exit_pilot_report(
        cfg=cfg,
        ticker=args.ticker,
        submit_live=bool(args.submit_live),
        use_live_exchange_rules_preview=bool(args.use_live_exchange_rules_preview),
        one_shot_actual_exit_submit=bool(args.one_shot_actual_exit_submit),
        one_shot_arm_ack=args.one_shot_arm_ack,
        d3_human_ack=args.d3_human_ack,
        require_position_id=args.require_position_id,
        require_plan_id=args.require_plan_id,
        require_plan_fingerprint=args.require_plan_fingerprint,
        order_store=OrderStore(path=args.order_store, log_path=args.order_events),
        state_store=StateStore(),
        coinbase_client=client,
        exchange_rules=exchange_rules,
        exchange_rules_context=exchange_rules_context,
        exchange_rules_fetch_error=exchange_rules_fetch_error,
        audit_path=args.audit_path,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print("D.3 controlled TP1 reduce-only SELL pilot")
        print("=========================================")
        print("status:", report.get("status"))
        print("ticker:", report.get("ticker"))
        print("submit_live:", report.get("submit_live"))
        print("selected_exit_label:", report.get("selected_exit_label"))
        print("selected_sell_base:", report.get("selected_sell_base"))
        print("selected_limit_price:", report.get("selected_limit_price"))
        print("exchange_rules_context:", report.get("exchange_rules_context"))
        print("base_increment:", report.get("base_increment"))
        print("quote_increment:", report.get("quote_increment"))
        print("min_order_quote:", report.get("min_order_quote"))
        print("live_submission_attempted:", report.get("live_submission_attempted"))
        print("live_order_submitted:", report.get("live_order_submitted"))
        print("blockers:", report.get("blockers"))
        print("warnings:", report.get("warnings"))
        print("one_shot_actual_exit_submit_armed_process_local:", report.get("one_shot_actual_exit_submit_armed_process_local"))
        print("one_shot_actual_exit_submit_blockers:", report.get("one_shot_actual_exit_submit_blockers"))
        print("required_position_id:", report.get("required_position_id"))
        print("required_plan_id:", report.get("required_plan_id"))
        print("required_plan_fingerprint:", report.get("required_plan_fingerprint"))

    if report.get("status") == "d3_controlled_exit_pilot_blocked":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
