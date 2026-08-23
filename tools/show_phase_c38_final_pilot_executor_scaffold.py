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
from bot.phase_c38_final_pilot_executor_scaffold import build_phase_c38_final_pilot_executor_report, C38_HUMAN_GO_ACK


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Phase-C C.3.8 final pilot executor scaffold/readiness.")
    parser.add_argument("--ticker", default="BTC-USDC", help="Pilot ticker to inspect, e.g. BTC-USDC")
    parser.add_argument("--json", action="store_true", help="Print full JSON report")
    parser.add_argument("--risk-dir", default=None, help="Optional directory with deterministic live-risk snapshots")
    parser.add_argument("--executor-mode", default="dry_run", help="Default dry_run; final live mode is intentionally explicit")
    parser.add_argument("--human-go-ack", default="", help="Exact human go ack; normally empty in C.3.8 dry-run")
    parser.add_argument("--submit-live", action="store_true", help="Request submit_live=True; still blocked unless every hardlock passes")
    parser.add_argument("--show-ack-token", action="store_true", help="Print required human-go token for later manual final pilot planning")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    report = build_phase_c38_final_pilot_executor_report(
        cfg=cfg,
        ticker=args.ticker,
        risk_dir=args.risk_dir,
        executor_mode=args.executor_mode,
        human_go_ack=args.human_go_ack,
        submit_live=bool(args.submit_live),
        coinbase_client=None,
    )

    print("Phase-C C.3.8 final pilot executor scaffold + double hardlock")
    print("================================================================")
    print("config_ok:", report.get("config_ok"))
    print("status:", report.get("status"))
    print("selected_ticker:", report.get("selected_ticker"))
    print("executor_mode:", report.get("executor_mode"))
    print("can_attempt_live_submit:", report.get("can_attempt_live_submit"))
    print("actual_coinbase_submit_currently_enabled:", report.get("actual_coinbase_submit_currently_enabled"))
    print("submit_live_argument:", report.get("submit_live_argument"))
    print("human_go_ack_ok:", report.get("human_go_ack_ok"))
    print("coinbase_client_provided:", report.get("coinbase_client_provided"))
    print("live_submission_attempted_by_this_tool:", report.get("live_submission_attempted_by_this_tool"))
    print("live_order_submitted:", report.get("live_order_submitted"))
    print()
    hardlocks = report.get("hardlock_assessment") or {}
    print("Hardlock blockers:", json.dumps(hardlocks.get("blockers") or [], ensure_ascii=False))
    print("Hardlock warnings:", json.dumps(hardlocks.get("warnings") or [], ensure_ascii=False))
    print("C.3.7 summary:", json.dumps(report.get("c37_summary") or {}, ensure_ascii=False))
    print("C.3.6 summary:", json.dumps(report.get("c36_summary") or {}, ensure_ascii=False))
    print("Payload summary:", json.dumps(report.get("payload_preview_summary") or {}, ensure_ascii=False))
    if args.show_ack_token:
        print("Required future human-go token:", C38_HUMAN_GO_ACK)
    print()
    print("Safety: C.3.8 scaffold is standaard dry-run/no-client/no-submit. Geen .env-wijziging, geen live exit, geen follower lifecycle.")
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
