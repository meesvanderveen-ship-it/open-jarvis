#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.pending_order_intents import PendingOrderIntentStore
from bot.phase_c_pilot_readiness import summarize_phase_c_submit_audit
from bot.phase_c34_candidate_snapshot import build_phase_c34_candidate_snapshot_report


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


def _write_candidate_file(report: Dict[str, Any], output: str | None) -> str | None:
    if not output:
        return None
    payload = report.get("candidate_file_payload") if isinstance(report.get("candidate_file_payload"), dict) else {}
    if not isinstance(payload.get("candidate"), dict):
        raise RuntimeError("Geen candidate payload beschikbaar om te schrijven.")
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(payload.get("candidate"), f, ensure_ascii=False, indent=2, sort_keys=True)
    tmp.replace(p)
    return str(p)


def main() -> int:
    parser = argparse.ArgumentParser(description="C.3.4 candidate snapshot extractor/generator (read-only, no submit)")
    parser.add_argument("--ticker", required=True, help="Pilot ticker, bijvoorbeeld BTC-USDC")
    parser.add_argument("--analysis-log", default="logs/analysis.jsonl")
    parser.add_argument("--execution-plan-log", default="logs/execution_plans.jsonl")
    parser.add_argument("--pending-intents", default="state/pending_order_intents.json")
    parser.add_argument("--order-events", default="logs/order_events.jsonl")
    parser.add_argument("--paper-manager-log", default="logs/paper_order_manager.jsonl")
    parser.add_argument("--risk-json", default=None, help="Optioneel pad naar echte deterministic live-risk JSON; C.3.4 verzint dit nooit zelf")
    parser.add_argument("--max-lines", type=int, default=2000)
    parser.add_argument("--max-quote", default="10.00")
    parser.add_argument("--output", default=None, help="Optioneel: schrijf alleen de candidate JSON naar dit pad")
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
    live_risk_result = _load_json(args.risk_json) if args.risk_json else None

    report = build_phase_c34_candidate_snapshot_report(
        cfg=cfg,
        ticker=args.ticker,
        analysis_log_path=args.analysis_log,
        execution_plan_log_path=args.execution_plan_log,
        pending_intents_path=args.pending_intents,
        order_events_path=args.order_events,
        paper_manager_path=args.paper_manager_log,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit,
        live_risk_result=live_risk_result,
        max_quote=args.max_quote,
        max_lines=args.max_lines,
    )

    written = None
    if args.output:
        written = _write_candidate_file(report, args.output)
        report["candidate_output_path"] = written

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if not report.get("actual_coinbase_submit_currently_enabled") else 2

    print("Phase-C C.3.4 candidate snapshot generator / extractor")
    print("======================================================")
    print(f"config_ok: True")
    print(f"ticker: {report.get('ticker')}")
    print(f"status: {report.get('status')}")
    print(f"candidate_snapshot_extracted: {report.get('candidate_snapshot_extracted')}")
    print(f"candidate_snapshot_structural_extraction_ready: {report.get('candidate_snapshot_structural_extraction_ready')}")
    print(f"final_preflight_snapshot_ready: {report.get('final_preflight_snapshot_ready')}")
    print(f"actual_coinbase_submit_currently_enabled: {report.get('actual_coinbase_submit_currently_enabled')}")
    print(f"live_submission_attempted_by_this_tool: {report.get('live_submission_attempted_by_this_tool')}")
    print(f"live_order_submitted: {report.get('live_order_submitted')}")
    print()
    print("Blockers:", json.dumps(report.get("blockers", []), ensure_ascii=False))
    print("Warnings:", json.dumps(report.get("warnings", []), ensure_ascii=False))
    print()
    sources = report.get("sources") if isinstance(report.get("sources"), dict) else {}
    for name, src in sources.items():
        if isinstance(src, dict):
            print(f"Source {name}: found={src.get('found')} generated_at={src.get('generated_at')}")
    if written:
        print(f"\nCandidate JSON geschreven naar: {written}")
    print("\nSafety: C.3.4 leest logs/state en kan een candidate JSON schrijven, maar doet geen Coinbase call, geen .env-wijziging en geen order.")
    return 0 if not report.get("actual_coinbase_submit_currently_enabled") else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
