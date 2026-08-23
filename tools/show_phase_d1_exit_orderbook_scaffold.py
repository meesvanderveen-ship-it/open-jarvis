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
from bot.order_store import OrderStore
from bot.phase_d1_exit_orderbook_scaffold import build_phase_d1_status_report
from bot.state_store import StateStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Show D.1 exit orderbook scaffold status")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    report = build_phase_d1_status_report(
        cfg=cfg,
        ticker=args.ticker,
        order_store=OrderStore(),
        state_store=StateStore(),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0

    print("Phase D.1 exit orderbook scaffold + reduce-only fill bridge")
    print("===========================================================")
    print(f"ticker: {report.get('ticker')}")
    print(f"open_position_count: {report.get('open_position_count')}")
    print(f"selected_position_present: {report.get('selected_position_present')}")
    cfg_view = report.get("config") or {}
    print(f"enable_phase_d1_exit_orderbook_scaffold: {cfg_view.get('enable_phase_d1_exit_orderbook_scaffold')}")
    print(f"enable_phase_d1_actual_exit_submit: {cfg_view.get('enable_phase_d1_actual_exit_submit')}")
    print(f"enable_live_exit_orders: {cfg_view.get('enable_live_exit_orders')}")
    print(f"autonomous_allow_exits: {cfg_view.get('autonomous_allow_exits')}")
    print(f"phase_d1_max_exit_order_quote: {cfg_view.get('phase_d1_max_exit_order_quote')}")
    print(f"phase_d1_max_open_exit_orders: {cfg_view.get('phase_d1_max_open_exit_orders')}")
    print("Local live exit orders:", json.dumps(report.get("local_live_exit_order_counts"), ensure_ascii=False))
    readiness = report.get("exit_readiness") or {}
    print("Exit readiness:", readiness.get("status", "no_position_for_selected_ticker"))
    if readiness:
        print("Readiness blockers:", json.dumps(readiness.get("blockers") or [], ensure_ascii=False))
        print("Readiness warnings:", json.dumps(readiness.get("warnings") or [], ensure_ascii=False))
    payload = report.get("exit_payload_preview") or {}
    if payload:
        print("Payload accepted:", payload.get("accepted"))
        print("Payload side:", payload.get("side"))
        print("Payload estimated quote:", payload.get("estimated_quote_value"))
    recon = report.get("fill_reconciliation_preview") or {}
    print("Fill reconciliation preview status:", recon.get("status"))
    print("local_live_exit_orders_seen:", recon.get("local_live_exit_orders_seen"))
    print("actions:", len(recon.get("actions") or []))
    print("errors:", len(recon.get("errors") or []))
    print("\nSafety: D.1 is reduce-only scaffold. Geen live exit-submit, geen buy, max 25 USDC exit-preview, max 4 open exit-orders.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
