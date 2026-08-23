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
from bot.phase_d3_controlled_live_exits import D3_ACK, build_phase_d3_controlled_live_exit_report
from bot.state_store import StateStore
from bot.order_store import OrderStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Phase D.3 controlled live reduce-only exit readiness")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--sample-position", action="store_true", help="Gebruik een synthetische D.3 positie-preview")
    parser.add_argument("--submit-live", action="store_true", help="Probeert alleen live submit als alle D.3 flags, ACK en client beschikbaar zijn")
    parser.add_argument("--ack", default="", help="D.3 human ACK string; vereist voor live submit")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    report = build_phase_d3_controlled_live_exit_report(
        cfg=cfg,
        ticker=args.ticker,
        state_store=StateStore(),
        order_store=OrderStore(),
        sample_position=args.sample_position,
        submit_live=args.submit_live,
        human_ack=args.ack,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    print("Phase D.3 controlled live reduce-only exits")
    print("============================================")
    print(f"status: {report.get('status')}")
    print(f"ticker: {report.get('ticker')}")
    print(f"position_present: {report.get('position_present')}")
    print(f"plan_present: {report.get('plan_present')}")
    print(f"d2_plan_source: {report.get('d2_plan_source')}")
    print(f"enable_phase_d3_controlled_live_exits: {report.get('enable_phase_d3_controlled_live_exits')}")
    print(f"enable_phase_d3_actual_exit_submit: {report.get('enable_phase_d3_actual_exit_submit')}")
    print(f"enable_live_exit_orders: {report.get('enable_live_exit_orders')}")
    print(f"autonomous_allow_exits: {report.get('autonomous_allow_exits')}")
    print(f"phase_c_disable_exit_limit_orders: {report.get('phase_c_disable_exit_limit_orders')}")
    print(f"live_submission_attempted: {report.get('live_submission_attempted')}")
    print(f"live_order_submitted: {report.get('live_order_submitted')}")
    print()
    print(f"Blockers: {json.dumps(report.get('blockers', []), sort_keys=True)}")
    print(f"Warnings: {json.dumps(report.get('warnings', []), sort_keys=True)}")
    intent = report.get("selected_exit_intent") or {}
    if intent:
        print("Selected exit intent:", json.dumps(intent, sort_keys=True))
    readiness = report.get("readiness") or {}
    if readiness:
        print("Readiness:", json.dumps({
            "status": readiness.get("status"),
            "ready": readiness.get("ready"),
            "submit_armed": readiness.get("submit_armed"),
            "sell_base": readiness.get("sell_base"),
            "estimated_quote_value": readiness.get("estimated_quote_value"),
        }, sort_keys=True))
    print()
    print("Safety: D.3 kan pas live SELL submitten met ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=true, ENABLE_LIVE_EXIT_ORDERS=true, AUTONOMOUS_ALLOW_EXITS=true, PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=false, --submit-live en exacte ACK:")
    print(D3_ACK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
