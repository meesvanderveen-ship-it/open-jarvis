#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.pending_order_intents import PendingOrderIntentStore
from bot.phase_c31_go_no_go import build_phase_c31_go_no_go_report
from bot.phase_c_pilot_readiness import summarize_phase_c_submit_audit


def _load_json(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"JSON-bestand niet gevonden: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON-bestand moet een object bevatten: {p}")
    return data


def _safe_summary(store: Any) -> Dict[str, Any]:
    try:
        summary = store.summary()
        return summary if isinstance(summary, dict) else {}
    except Exception as exc:
        return {"summary_error": str(exc)}


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

    order_store = OrderStore(path=args.open_orders_path, log_path=args.order_log_path)
    order_summary = _safe_summary(order_store)
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
    candidate = _load_json(args.candidate_json)

    report = build_phase_c31_go_no_go_report(
        cfg=cfg,
        pending_summary=pending_summary,
        order_summary=order_summary,
        submit_audit_summary=submit_audit,
        ticker=args.ticker,
        candidate=candidate,
        require_candidate_guard=not args.config_only,
    )
    report["config_ok"] = config_ok
    if config_error:
        report["config_error"] = config_error
    if args.config_only:
        report["mode"] = "config_only_no_candidate_guard"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="C.3.1 one-ticker live-pilot go/no-go voorbereiding zonder Coinbase submit.")
    parser.add_argument("--json", action="store_true", help="Print volledige JSON-output.")
    parser.add_argument("--ticker", default=None, help="Optionele pilot-ticker; standaard uit PHASE_C_ALLOWED_TICKERS/C.3.0-report.")
    parser.add_argument("--candidate-json", default=None, help="Optioneel JSON-bestand met verse candidate snapshot voor guard-check.")
    parser.add_argument("--config-only", action="store_true", help="Laat candidate_guard ontbreken zonder blocker; alleen configuratievoorbereiding.")
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

    print("Phase-C C.3.1 one-ticker live-pilot go/no-go voorbereiding")
    print("================================================================")
    print("config_ok:", report.get("config_ok"))
    if report.get("config_error"):
        print("config_error:", report.get("config_error"))
    print("mode:", report.get("mode", "full_go_no_go_requires_candidate_guard"))
    print("status:", report.get("status"))
    print("pilot_ticker:", report.get("pilot_ticker"))
    print("ready_for_human_final_c31_review:", report.get("ready_for_human_final_c31_review"))
    print("final_go_no_go_locked_until_human_enables_actual_submit:", report.get("final_go_no_go_locked_until_human_enables_actual_submit"))
    print("actual_coinbase_submit_currently_enabled:", report.get("actual_coinbase_submit_currently_enabled"))
    print("live_submission_attempted_by_this_tool:", report.get("live_submission_attempted_by_this_tool"))
    print("live_order_submitted:", report.get("live_order_submitted"))
    print()
    print("Blockers:", "geen" if not report.get("blockers") else json.dumps(report.get("blockers"), ensure_ascii=False))
    print("Warnings:", "geen" if not report.get("warnings") else json.dumps(report.get("warnings"), ensure_ascii=False))
    print()
    env_preview = report.get("env_preview") or {}
    print("Staged preflight .env preview — NIET automatisch toegepast:")
    for line in env_preview.get("staged_preflight_env") or []:
        print("  " + line)
    print()
    print("Final actual-submit arm blijft handmatig en apart:")
    for line in env_preview.get("final_actual_submit_arm_env") or []:
        print("  " + line)
    print()
    print("Safety: deze tool is read-only, wijzigt geen .env, plaatst geen orders en mag actual submit niet zelfstandig aanzetten.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
