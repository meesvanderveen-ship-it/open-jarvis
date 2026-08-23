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
from bot.phase_d3_full_residual_exit_submit_scaffold import (
    build_phase_d3_full_residual_exit_submit_scaffold_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gated scaffold for a future full residual D.3 exit submit. Dry-run by default."
    )
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--limit-price", required=True)
    parser.add_argument("--base-increment", required=True)
    parser.add_argument("--base-min-size", required=True)
    parser.add_argument("--quote-min-size", required=True)
    parser.add_argument("--price-increment", required=True)
    parser.add_argument("--live-base-available", required=True)
    parser.add_argument("--confirm-route", default="")
    parser.add_argument("--confirm-label", default="")
    parser.add_argument("--submit-live", action="store_true")
    parser.add_argument("--residual-submit-ack", default="")
    parser.add_argument("--d3-human-ack", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = BotConfig()
    cfg.validate()
    report = build_phase_d3_full_residual_exit_submit_scaffold_report(
        cfg=cfg,
        ticker=args.ticker,
        limit_price=args.limit_price,
        base_increment=args.base_increment,
        base_min_size=args.base_min_size,
        quote_min_size=args.quote_min_size,
        price_increment=args.price_increment,
        live_base_available=args.live_base_available,
        submit_live=args.submit_live,
        residual_submit_ack=args.residual_submit_ack,
        d3_human_ack=args.d3_human_ack,
        confirm_route=args.confirm_route,
        confirm_label=args.confirm_label,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print("Phase D.3 full residual exit submit scaffold")
        print("============================================")
        print("status:", report.get("status"))
        print("selected_route:", report.get("selected_route"))
        print("candidate_label:", report.get("candidate_label"))
        print("submit_live_requested:", report.get("submit_live_requested"))
        print("ready_for_operator_live_ack:", report.get("ready_for_operator_live_ack"))
        print("live_submit_allowed:", report.get("live_submit_allowed"))
        print("safety_blockers:", report.get("safety_blockers"))
        print("live_gate_blockers:", report.get("live_gate_blockers"))
        print("live_order_action_performed:", report.get("live_order_action_performed"))
        print("coinbase_write_performed:", report.get("coinbase_write_performed"))
        print("state_write_performed:", report.get("state_write_performed"))
    submit_result = report.get("submit_result") or {}
    if submit_result.get("live_order_submitted"):
        return 0
    if report.get("safety_blockers"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
