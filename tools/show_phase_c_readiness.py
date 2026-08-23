#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.pending_order_intents import PendingOrderIntentStore
from bot.phase_c_live_guard import summarize_phase_c_readiness


def _safe_summary(store: Any) -> Dict[str, Any]:
    try:
        data = store.summary()
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        return {"error": str(exc)}


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = BotConfig()
    try:
        cfg.validate()
        config_ok = True
        config_error = None
    except Exception as exc:
        config_ok = False
        config_error = str(exc)

    order_store = OrderStore(
        path=args.open_orders_path,
        log_path=args.order_log_path,
        max_orders=max(50, int(getattr(cfg, "order_store_max_records", 2000))),
    )
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
    order_summary = _safe_summary(order_store)
    pending_summary = _safe_summary(pending_store)
    report = summarize_phase_c_readiness(cfg=cfg, pending_summary=pending_summary, order_summary=order_summary)
    report["config_ok"] = config_ok
    if config_error:
        report["config_error"] = config_error
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Toon Phase-C live-entry readiness zonder orders te plaatsen.")
    parser.add_argument("--json", action="store_true", help="Print volledige JSON-output.")
    parser.add_argument("--open-orders-path", default="state/open_orders.json")
    parser.add_argument("--order-log-path", default="logs/order_events.jsonl")
    parser.add_argument("--pending-intents-path", default="state/pending_order_intents.json")
    parser.add_argument("--pending-intents-log-path", default="logs/pending_order_intents.jsonl")
    args = parser.parse_args()

    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0

    cfg = report.get("config", {})
    pending = report.get("pending_order_intents", {})
    orders = report.get("orders", {})
    print("Phase-C live-entry readiness")
    print("==========================================")
    print("config_ok:", report.get("config_ok"))
    if report.get("config_error"):
        print("config_error:", report.get("config_error"))
    print("phase_c_master_switch:", cfg.get("enable_phase_c_live_small_limit_orders"))
    print("execution_mode:", cfg.get("execution_mode"))
    print("live_limit_orders:", cfg.get("enable_live_limit_orders"))
    print("live_entry_orders:", cfg.get("enable_live_entry_orders"))
    print("live_exit_orders:", cfg.get("enable_live_exit_orders"))
    print("allowed_tickers:", cfg.get("phase_c_allowed_tickers"))
    print("max_order_quote:", cfg.get("phase_c_max_order_quote"))
    print("live_submit_infrastructure:", cfg.get("enable_phase_c_live_submit_infrastructure"))
    print("actual_coinbase_submit:", cfg.get("enable_phase_c_actual_coinbase_submit"))
    print("live_order_post_only:", cfg.get("phase_c_live_order_post_only"))
    print()
    print("Orders")
    print(f"total: {orders.get('total')} | open: {orders.get('open')} | diagnostics: {orders.get('diagnostics')}")
    print()
    print("Pending order-intents")
    print(f"total: {pending.get('total')} | open_intents: {pending.get('open_intents')}")
    print("trigger_ready_current:", json.dumps(pending.get("trigger_ready_current", []), sort_keys=True, default=str))
    print("needs_fresh_analysis_current:", json.dumps(pending.get("needs_fresh_analysis_current", []), sort_keys=True, default=str))
    print("promotion_ready_current:", json.dumps(pending.get("promotion_ready_current", []), sort_keys=True, default=str))
    print()
    blockers = report.get("blockers", [])
    print("Blockers:", "geen" if not blockers else json.dumps(blockers, sort_keys=True))
    print("Safety: read-only report, geen Coinbase submit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
