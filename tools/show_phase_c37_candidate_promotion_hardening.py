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
from bot.phase_c37_candidate_promotion_hardening import build_phase_c37_candidate_promotion_hardening_report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Show Phase-C C.3.7 candidate promotion hardening + live-risk bridge report.")
    parser.add_argument("--ticker", action="append", dest="tickers", help="Ticker to inspect. Can be passed multiple times. Defaults to pending/config watch tickers.")
    parser.add_argument("--risk-dir", default=None, help="Optional directory with deterministic live-risk JSON files keyed by ticker.")
    parser.add_argument("--analysis-log", default="logs/analysis.jsonl")
    parser.add_argument("--execution-plan-log", default="logs/execution_plans.jsonl")
    parser.add_argument("--pending-intents", default="state/pending_order_intents.json")
    parser.add_argument("--order-events", default="logs/order_events.jsonl")
    parser.add_argument("--paper-manager-log", default="logs/paper_order_manager.jsonl")
    parser.add_argument("--max-lines", type=int, default=2000)
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    cfg = BotConfig()
    cfg.validate()
    report = build_phase_c37_candidate_promotion_hardening_report(
        cfg=cfg,
        tickers=args.tickers,
        ticker=args.tickers[0] if args.tickers and len(args.tickers) == 1 else None,
        risk_dir=args.risk_dir,
        analysis_log_path=args.analysis_log,
        execution_plan_log_path=args.execution_plan_log,
        pending_intents_path=args.pending_intents,
        order_events_path=args.order_events,
        paper_manager_path=args.paper_manager_log,
        max_lines=args.max_lines,
    )

    print("Phase-C C.3.7 candidate promotion hardening + live-risk bridge")
    print("=================================================================")
    print("config_ok:", report.get("config_ok"))
    print("status:", report.get("status"))
    print("selected_ticker:", report.get("selected_ticker"))
    print("actionable_preflight_ready_tickers:", report.get("actionable_preflight_ready_tickers"))
    print("blocked_or_context_tickers:", report.get("blocked_or_context_tickers"))
    print("actual_coinbase_submit_currently_enabled:", report.get("actual_coinbase_submit_currently_enabled"))
    print("live_submission_attempted_by_this_tool:", report.get("live_submission_attempted_by_this_tool"))
    print("live_order_submitted:", report.get("live_order_submitted"))
    print()
    print("Counts:", json.dumps(report.get("counts", {}), ensure_ascii=False))
    print("Risk bridge:", json.dumps(report.get("live_risk_bridge", {}), ensure_ascii=False))
    print("Blockers:", json.dumps(report.get("blockers", []), ensure_ascii=False))
    print("Warnings:", json.dumps(report.get("warnings", []), ensure_ascii=False))
    print()
    for item in report.get("candidate_assessments", []) or []:
        print(
            f"- {item.get('ticker')}: {item.get('promotion_status')} | "
            f"judge={item.get('judge_decision')}/{item.get('judge_side')} | "
            f"action={item.get('order_intent_action')} | "
            f"suppress_payload={item.get('payload_preview_should_be_suppressed')} | "
            f"categories={item.get('blocker_categories')}"
        )
    print()
    safe_preview = report.get("safe_c36_payload_preview") or {}
    print("Safe C.3.6 payload preview:", json.dumps(safe_preview, ensure_ascii=False))
    print()
    print("Safety: C.3.7 is read-only. Geen .env-wijziging, geen Coinbase call, geen order, geen risk-fabricage, actual submit blijft false.")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
