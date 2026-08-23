#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.pending_order_intents import PendingOrderIntentStore
from bot.phase_c_pilot_readiness import summarize_phase_c_submit_audit
from bot.phase_c36_final_pilot_dry_run import build_phase_c36_final_pilot_dry_run_report


def _safe_summary(store: Any) -> Dict[str, Any]:
    try:
        value = store.summary()
        return value if isinstance(value, dict) else {}
    except Exception as exc:
        return {"summary_error": str(exc)}


def _load_json(path: str | None) -> Dict[str, Any]:
    if not path:
        return {}
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        return {"load_error": str(exc), "path": path}


def main() -> int:
    parser = argparse.ArgumentParser(description="Show Phase-C C.3.6 final pilot-run dry-run hardlock runbook.")
    parser.add_argument("--ticker", default="", help="Preferred pilot ticker, e.g. BTC-USDC. If omitted, first preflight-ready ticker is selected.")
    parser.add_argument("--analysis-log", default="logs/analysis.jsonl")
    parser.add_argument("--execution-plan-log", default="logs/execution_plans.jsonl")
    parser.add_argument("--pending-intents", default="state/pending_order_intents.json")
    parser.add_argument("--order-events", default="logs/order_events.jsonl")
    parser.add_argument("--paper-manager-log", default="logs/paper_order_manager.jsonl")
    parser.add_argument("--risk-json", default=None, help="Optional deterministic live-risk JSON for the selected ticker.")
    parser.add_argument("--risk-dir", default=None, help="Optional directory containing per-ticker deterministic live-risk JSON files.")
    parser.add_argument("--max-quote", default="10.00")
    parser.add_argument("--max-lines", type=int, default=2000)
    parser.add_argument("--human-go-ack", action="store_true", help="Record that a human reviewed this dry-run report. Does not enable submit.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()

    pending_store = PendingOrderIntentStore(
        path=args.pending_intents,
        max_records=getattr(cfg, "paper_pending_intent_max_records", 500),
        enabled=getattr(cfg, "enable_paper_pending_order_intents", True),
    )
    order_store = OrderStore()
    pending_summary = _safe_summary(pending_store)
    order_summary = _safe_summary(order_store)
    submit_audit = summarize_phase_c_submit_audit()

    live_risk_by_ticker: Dict[str, Dict[str, Any]] = {}
    ticker = args.ticker.upper().replace("/", "-").strip()
    if args.risk_json and ticker:
        live_risk_by_ticker[ticker] = _load_json(args.risk_json)

    report = build_phase_c36_final_pilot_dry_run_report(
        cfg=cfg,
        ticker=ticker or None,
        analysis_log_path=args.analysis_log,
        execution_plan_log_path=args.execution_plan_log,
        pending_intents_path=args.pending_intents,
        order_events_path=args.order_events,
        paper_manager_path=args.paper_manager_log,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit,
        live_risk_by_ticker=live_risk_by_ticker,
        risk_dir=args.risk_dir,
        max_quote=args.max_quote,
        max_lines=args.max_lines,
        require_human_go_ack=args.human_go_ack,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if not report.get("actual_coinbase_submit_currently_enabled") else 2

    print("Phase-C C.3.6 final pilot-run dry-run + hardlock runbook")
    print("=========================================================")
    print("config_ok: True")
    print(f"status: {report.get('status')}")
    print(f"selected_ticker: {report.get('selected_ticker')}")
    print(f"dry_run_ready_no_submit: {report.get('dry_run_ready_no_submit')}")
    print(f"ready_for_future_final_human_pilot_review: {report.get('ready_for_future_final_human_pilot_review')}")
    print(f"actual_coinbase_submit_currently_enabled: {report.get('actual_coinbase_submit_currently_enabled')}")
    print(f"live_submission_attempted_by_this_tool: {report.get('live_submission_attempted_by_this_tool')}")
    print(f"live_order_submitted: {report.get('live_order_submitted')}")
    print()
    print("Blockers:", json.dumps(report.get("blockers", []), ensure_ascii=False))
    print("Warnings:", json.dumps(report.get("warnings", []), ensure_ascii=False))
    print("C.3.5 summary:", json.dumps(report.get("c35_summary", {}), ensure_ascii=False))
    print()
    print("Human go/no-go checklist:")
    for item in report.get("human_go_no_go_checklist", []):
        print(f"  - {item}")
    print()
    print("Staged preflight .env preview — NIET automatisch toepassen:")
    for line in (report.get("env_preview", {}) or {}).get("staged_preflight_env_lines", []):
        print(f"  {line}")
    print("Final actual-submit arm blijft verboden in C.3.6 dry-run:")
    print(f"  {(report.get('env_preview', {}) or {}).get('final_actual_submit_arm_line_not_for_c36')}")
    print("\nSafety: C.3.6 is dry-run/runbook only. Geen .env-wijziging, geen Coinbase call, geen order, actual submit blijft false.")
    return 0 if not report.get("actual_coinbase_submit_currently_enabled") else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
