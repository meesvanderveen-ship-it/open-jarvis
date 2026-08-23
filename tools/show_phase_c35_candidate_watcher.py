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
from bot.phase_c35_candidate_watcher import build_phase_c35_candidate_watcher_report


def _safe_summary(store: Any) -> Dict[str, Any]:
    try:
        data = store.summary()
        return data if isinstance(data, dict) else {}
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


def _parse_tickers(raw: str | None) -> List[str]:
    if not raw:
        return []
    return [x.strip().upper().replace("/", "-") for x in raw.split(",") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="C.3.5 candidate watcher + preflight pipeline (read-only, no submit)")
    parser.add_argument("--ticker", default=None, help="Één ticker, bijvoorbeeld BTC-USDC")
    parser.add_argument("--tickers", default=None, help="Comma-separated tickers, bijvoorbeeld BTC-USDC,ETH-USDC")
    parser.add_argument("--analysis-log", default="logs/analysis.jsonl")
    parser.add_argument("--execution-plan-log", default="logs/execution_plans.jsonl")
    parser.add_argument("--pending-intents", default="state/pending_order_intents.json")
    parser.add_argument("--order-events", default="logs/order_events.jsonl")
    parser.add_argument("--paper-manager-log", default="logs/paper_order_manager.jsonl")
    parser.add_argument("--risk-json", default=None, help="Optioneel: echte deterministic live-risk JSON voor --ticker")
    parser.add_argument("--risk-dir", default=None, help="Optioneel: directory met <ticker>.json risk snapshots")
    parser.add_argument("--max-lines", type=int, default=2000)
    parser.add_argument("--max-quote", default="10.00")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()

    tickers = _parse_tickers(args.tickers)
    if args.ticker:
        tickers.insert(0, args.ticker)

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
    if args.risk_json and args.ticker:
        live_risk_by_ticker[args.ticker.upper().replace("/", "-")] = _load_json(args.risk_json)

    report = build_phase_c35_candidate_watcher_report(
        cfg=cfg,
        tickers=tickers or None,
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
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if not report.get("actual_coinbase_submit_currently_enabled") else 2

    print("Phase-C C.3.5 candidate watcher + preflight pipeline")
    print("====================================================")
    print("config_ok: True")
    print(f"status: {report.get('status')}")
    print(f"watch_tickers: {report.get('watch_tickers')}")
    print(f"any_preflight_ready_no_submit: {report.get('any_preflight_ready_no_submit')}")
    print(f"preflight_ready_tickers: {report.get('preflight_ready_tickers')}")
    print(f"blocked_candidate_tickers: {report.get('blocked_candidate_tickers')}")
    print(f"no_candidate_tickers: {report.get('no_candidate_tickers')}")
    print(f"actual_coinbase_submit_currently_enabled: {report.get('actual_coinbase_submit_currently_enabled')}")
    print(f"live_submission_attempted_by_this_tool: {report.get('live_submission_attempted_by_this_tool')}")
    print(f"live_order_submitted: {report.get('live_order_submitted')}")
    print()
    print("Counts:", json.dumps(report.get("counts", {}), ensure_ascii=False))
    print("Blockers:", json.dumps(report.get("blockers", []), ensure_ascii=False))
    print("Warnings:", json.dumps(report.get("warnings", []), ensure_ascii=False))
    print()
    for item in report.get("candidate_summaries", []):
        print(f"- {item.get('ticker')}: {item.get('watch_status')} | judge={item.get('judge_decision')}/{item.get('judge_side')} | action={item.get('order_intent_action')} | blockers={item.get('blockers')}")
    print("\nSafety: C.3.5 is read-only. Geen .env-wijziging, geen Coinbase call, geen order, actual submit blijft false.")
    return 0 if not report.get("actual_coinbase_submit_currently_enabled") else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
