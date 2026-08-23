#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.phase_d31_lifecycle_readiness import D31_ENTRY_ARM_ACK, build_phase_d31_lifecycle_readiness_report
from bot.state_store import StateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Phase D.3.1 end-to-end lifecycle readiness.")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--require-actual-entry-submit", action="store_true", help="Treat readiness as a true arming validation requiring ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true and the D31 ACK.")
    parser.add_argument("--human-ack", default=os.getenv("PHASE_D31_HUMAN_ACK", ""))
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    report = build_phase_d31_lifecycle_readiness_report(
        cfg=cfg,
        ticker=args.ticker,
        order_store=OrderStore(),
        state_store=StateStore(),
        require_actual_entry_submit=bool(args.require_actual_entry_submit),
        human_ack=args.human_ack,
    )
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    entry = report.get("entry_readiness") or {}
    print("Phase D.3.1 end-to-end lifecycle readiness")
    print("================================================")
    print(f"status: {report.get('status')}")
    print(f"ticker: {report.get('ticker')}")
    print(f"ready_for_controlled_entry_only_arming: {report.get('ready_for_controlled_entry_only_arming')}")
    print(f"enable_phase_c_actual_coinbase_submit: {entry.get('config_flags', {}).get('enable_phase_c_actual_coinbase_submit')}")
    print(f"enable_live_entry_orders: {entry.get('config_flags', {}).get('enable_live_entry_orders')}")
    print(f"enable_live_exit_orders: {entry.get('config_flags', {}).get('enable_live_exit_orders')}")
    print(f"enable_phase_d3_actual_exit_submit: {entry.get('config_flags', {}).get('enable_phase_d3_actual_exit_submit')}")
    print(f"autonomous_entry_only_first: {entry.get('config_flags', {}).get('autonomous_entry_only_first')}")
    print(f"autonomous_allow_exits: {entry.get('config_flags', {}).get('autonomous_allow_exits')}")
    print(f"phase_c_disable_exit_limit_orders: {entry.get('config_flags', {}).get('phase_c_disable_exit_limit_orders')}")
    print(f"selected_manageable_position_count: {entry.get('selected_manageable_position_count')}")
    print(f"all_manageable_position_count: {entry.get('all_manageable_position_count')}")
    print(f"stack: {json.dumps(report.get('stack', {}), ensure_ascii=False, sort_keys=True)}")
    print(f"Blockers: {json.dumps(report.get('blockers', []), ensure_ascii=False)}")
    print(f"Warnings: {json.dumps(report.get('warnings', []), ensure_ascii=False)}")
    print()
    print("Safety: D.3.1 wijzigt geen .env en plaatst geen orders. Het controleert alleen of C.4.3 entry-only arming logisch veilig is, met D.2/D.3 exit-stack klaar maar exits uit.")
    print("ACK voor een echte arming-review:")
    print(D31_ENTRY_ARM_ACK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
