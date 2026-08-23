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
from bot.phase_c_pilot_readiness import summarize_phase_c_submit_audit
from bot.phase_c33_candidate_preflight import build_phase_c33_final_preflight_report


def _safe_summary(store: Any) -> Dict[str, Any]:
    try:
        data = store.summary()
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        return {"summary_error": str(exc)}


def _load_candidate(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"candidate JSON niet gevonden: {p}")
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("candidate JSON moet één object bevatten")
    return obj


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    config_ok = True
    config_error = None
    try:
        cfg = BotConfig()
        cfg.validate()
    except Exception as exc:
        cfg = BotConfig()
        config_ok = False
        config_error = f"{type(exc).__name__}: {exc}"

    order_store = OrderStore(
        path=args.open_orders_path,
        log_path=args.order_log_path,
        max_orders=max(50, int(getattr(cfg, "order_store_max_records", 2000))),
    )
    order_summary = _safe_summary(order_store)
    try:
        order_summary["open_entry_orders"] = order_store.open_entry_orders(ticker=args.ticker) if args.ticker else order_store.open_entry_orders()
    except Exception:
        try:
            order_summary["open_entry_orders"] = order_store.list_open_entry_orders()
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

    report = build_phase_c33_final_preflight_report(
        cfg=cfg,
        ticker=args.ticker,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit,
        candidate=candidate,
        max_quote=args.max_quote,
    )
    report["config_ok"] = config_ok
    if config_error:
        report["config_error"] = config_error
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="C.3.3 candidate-capture/final-preflight bridge zonder Coinbase submit.")
    parser.add_argument("--json", action="store_true", help="Print volledige JSON-output.")
    parser.add_argument("--ticker", required=True, help="Pilot-ticker, bijvoorbeeld BTC-USDC.")
    parser.add_argument("--candidate-json", default=None, help="Optioneel JSON-bestand met verse candidate snapshot.")
    parser.add_argument("--max-quote", default="10.00", help="Max quote cap voor staged config; default 10.00 USDC.")
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

    print("Phase-C C.3.3 candidate-capture / final-preflight bridge")
    print("===========================================================")
    print("config_ok:", report.get("config_ok"))
    if report.get("config_error"):
        print("config_error:", report.get("config_error"))
    print("ticker:", report.get("ticker"))
    print("status:", report.get("status"))
    print("final_preflight_snapshot_ready:", report.get("final_preflight_snapshot_ready"))
    print("ready_for_human_final_pilot_run_review:", report.get("ready_for_human_final_pilot_run_review"))
    print("actual_coinbase_submit_currently_enabled:", report.get("actual_coinbase_submit_currently_enabled"))
    print("live_submission_attempted_by_this_tool:", report.get("live_submission_attempted_by_this_tool"))
    print("live_order_submitted:", report.get("live_order_submitted"))
    print()
    print("Blockers:", "geen" if not report.get("blockers") else json.dumps(report.get("blockers"), ensure_ascii=False))
    print("Warnings:", "geen" if not report.get("warnings") else json.dumps(report.get("warnings"), ensure_ascii=False))
    print()
    candidate = report.get("candidate_snapshot") or {}
    print("Candidate snapshot:")
    print("  provided:", candidate.get("candidate_snapshot_provided"))
    print("  pending_intent_id:", candidate.get("pending_intent_id"))
    print("  fresh_analysis_id:", candidate.get("fresh_analysis_id"))
    print("  structural_ready:", candidate.get("candidate_snapshot_ready_for_guard"))
    guard = report.get("guard_summary") or {}
    print("Guard:")
    print("  candidate_guard_ready:", guard.get("candidate_guard_ready"))
    print("  guard_allows_live_submit:", guard.get("guard_allows_live_submit"))
    payload = report.get("payload_preview") or {}
    print("Payload preview:")
    print("  accepted:", payload.get("accepted"))
    print("  client_order_id:", payload.get("client_order_id"))
    print("  reject_reasons:", payload.get("reject_reasons"))
    print()
    print("Safety: C.3.3 is read-only. Geen .env-wijziging, geen Coinbase call, geen order, actual submit blijft false.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
