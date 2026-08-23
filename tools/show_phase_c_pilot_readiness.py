#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.pending_order_intents import PendingOrderIntentStore
from bot.phase_c_pilot_readiness import build_phase_c_pilot_readiness_report, summarize_phase_c_submit_audit


def _safe_summary(store: Any) -> Dict[str, Any]:
    try:
        data = store.summary()
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        return {"error": str(exc)}


def _load_candidate(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    p = Path(path)
    try:
        with p.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else {"load_error": "candidate_json_not_object"}
    except Exception as exc:
        return {"load_error": str(exc)}


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = BotConfig()
    config_ok = True
    config_error = None
    try:
        cfg.validate()
    except Exception as exc:
        config_ok = False
        config_error = str(exc)

    order_store = OrderStore(
        path=args.open_orders_path,
        log_path=args.order_log_path,
        max_orders=max(50, int(getattr(cfg, "order_store_max_records", 2000))),
    )
    order_summary = _safe_summary(order_store)
    try:
        open_entry_orders = order_store.open_entry_orders(ticker=args.ticker) if args.ticker else order_store.open_entry_orders()
        order_summary["open_entry_orders"] = open_entry_orders
    except Exception as exc:
        order_summary["open_entry_orders_error"] = str(exc)

    pending_store = PendingOrderIntentStore(
        path=args.pending_intents_path,
        log_path=args.pending_intents_log_path,
        max_records=max(50, int(getattr(cfg, "paper_pending_intent_max_records", 500))),
        enabled=True,
        max_replaced_per_ticker=int(getattr(cfg, "paper_pending_intent_max_replaced_per_ticker", 8)),
        final_retention_hours=int(getattr(cfg, "paper_pending_intent_final_retention_hours", 72)),
        dedupe_tolerance_pct=getattr(cfg, "paper_pending_intent_dedupe_tolerance_pct", "0.0025"),
        enable_dedupe_refresh=bool(getattr(cfg, "paper_pending_intent_enable_dedupe_refresh", True)),
    )
    pending_summary = _safe_summary(pending_store)
    submit_audit = summarize_phase_c_submit_audit(path=args.submit_audit_path, sample=args.sample)
    candidate = _load_candidate(args.candidate_json)

    report = build_phase_c_pilot_readiness_report(
        cfg=cfg,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit,
        pilot_ticker=args.ticker,
        candidate=candidate,
    )
    report["config_ok"] = config_ok
    if config_error:
        report["config_error"] = config_error
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="C.3.0 one-ticker pilot-readiness/checklist zonder Coinbase submit.")
    parser.add_argument("--json", action="store_true", help="Print volledige JSON-output.")
    parser.add_argument("--ticker", default=None, help="Optionele pilot-ticker; standaard: enige PHASE_C_ALLOWED_TICKERS-ticker.")
    parser.add_argument("--candidate-json", default=None, help="Optioneel JSON-bestand met verse analysis/execution_plan/order_intent/risk snapshot.")
    parser.add_argument("--sample", type=int, default=100, help="Aantal recente phase_c_live_submit auditregels.")
    parser.add_argument("--open-orders-path", default="state/open_orders.json")
    parser.add_argument("--order-log-path", default="logs/order_events.jsonl")
    parser.add_argument("--pending-intents-path", default="state/pending_order_intents.json")
    parser.add_argument("--pending-intents-log-path", default="logs/pending_order_intents.jsonl")
    parser.add_argument("--submit-audit-path", default="logs/phase_c_live_submit.jsonl")
    args = parser.parse_args()

    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False, default=str))
        return 0

    print("Phase-C C.3.0 one-ticker pilot readiness")
    print("================================================")
    print("config_ok:", report.get("config_ok"))
    if report.get("config_error"):
        print("config_error:", report.get("config_error"))
    print("pilot_ticker:", report.get("pilot_ticker"))
    print("pilot_config_ready:", report.get("pilot_config_ready"))
    print("submit_infrastructure_ready:", report.get("submit_infrastructure_ready"))
    print("actual_coinbase_submit_still_disabled:", report.get("actual_coinbase_submit_still_disabled"))
    print("runtime_candidate_ready:", report.get("runtime_candidate_ready"))
    print("candidate_guard_ready:", report.get("candidate_guard_ready"))
    print("c30_safe_to_continue_without_submit:", report.get("c30_safe_to_continue_without_submit"))
    print("overall_ready_for_future_c31_review:", report.get("overall_ready_for_future_c31_review"))
    print()
    print("Config blockers:", json.dumps((report.get("config_assessment") or {}).get("blockers", []), ensure_ascii=False))
    print("Runtime blockers:", json.dumps((report.get("runtime_assessment") or {}).get("blockers", []), ensure_ascii=False))
    print("Candidate guard blockers:", json.dumps((report.get("candidate_guard_assessment") or {}).get("blockers", []), ensure_ascii=False))
    print("Alle blockers:", "geen" if not report.get("blockers") else json.dumps(report.get("blockers"), ensure_ascii=False))
    print()
    runtime = report.get("runtime_assessment") or {}
    print("Orders:", json.dumps(runtime.get("orders", {}), sort_keys=True, ensure_ascii=False))
    print("Pending:", json.dumps(runtime.get("pending_order_intents", {}), sort_keys=True, ensure_ascii=False))
    print("Submit audit:", json.dumps(runtime.get("submit_audit", {}), sort_keys=True, ensure_ascii=False))
    print()
    print("Safety: C.3.0 is checklist/read-only. Geen Coinbase submit; actual submit moet false blijven.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
