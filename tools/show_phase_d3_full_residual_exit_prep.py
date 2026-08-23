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
from bot.phase_d3_full_residual_exit_prep import build_phase_d3_full_residual_exit_prep_report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only final-prep report for a future single full residual D.3 exit."
    )
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--limit-price", required=True)
    parser.add_argument("--base-increment", default="0.00000001")
    parser.add_argument("--base-min-size", default="0.00000001")
    parser.add_argument("--quote-min-size", default="1")
    parser.add_argument("--price-increment", default="0.01")
    parser.add_argument("--live-base-available", default="")
    parser.add_argument("--route-label", default="TP_CLOSE")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = BotConfig()
    cfg.validate()
    report = build_phase_d3_full_residual_exit_prep_report(
        cfg=cfg,
        ticker=args.ticker,
        limit_price=args.limit_price,
        base_increment=args.base_increment,
        base_min_size=args.base_min_size,
        quote_min_size=args.quote_min_size,
        price_increment=args.price_increment,
        live_base_available=args.live_base_available or None,
        route_label=args.route_label,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("Phase D.3 full residual exit final prep")
        print("========================================")
        print("status:", report.get("status"))
        print("ticker:", report.get("ticker"))
        print("route:", report.get("route"))
        print("route_label:", report.get("route_label"))
        print("rounded_sell_base:", report.get("rounded_sell_base"))
        print("limit_price:", report.get("limit_price"))
        print("estimated_quote_value:", report.get("estimated_quote_value"))
        print("live_base_sufficient:", report.get("live_base_sufficient"))
        print("blockers:", report.get("blockers"))
        print("warnings:", report.get("warnings"))
        print("future_live_submit_ack_required:", report.get("future_live_submit_ack_required"))
    return 2 if report.get("blockers") else 0


if __name__ == "__main__":
    raise SystemExit(main())
