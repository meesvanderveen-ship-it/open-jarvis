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
from bot.phase_c42_final_pre_live_autonomy_bridge import (
    C42_FINAL_ARM_ACK,
    C42_AUTONOMOUS_MODE_NAME,
    build_phase_c42_final_pre_live_autonomy_bridge_report,
)


def _load_snapshot(path: str | None):
    if not path:
        return None
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and isinstance(data.get("orders"), list):
        return data["orders"]
    if isinstance(data, list):
        return data
    raise SystemExit(f"Snapshot moet een lijst orders bevatten of {{'orders': [...]}}: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase C.4.2 final pre-live autonomy bridge for small live orderbook mode")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--live-orders-snapshot", default=None, help="Pad naar JSON snapshot met live orders; geen Coinbase call")
    parser.add_argument("--allow-coinbase-poll", action="store_true", help="Alleen voor latere diagnose; deze CLI geeft geen Coinbase client door")
    parser.add_argument("--risk-dir", default=None, help="Map met deterministic live-risk JSON snapshots")
    parser.add_argument("--order-store", default="state/open_orders.json")
    parser.add_argument("--order-events", default="logs/order_events.jsonl")
    parser.add_argument("--no-require-controlled-poll", action="store_true", help="Alleen voor lokale/snapshot tests; live go/no-go vereist controlled poll")
    parser.add_argument("--autonomous-mode", default="dry_run")
    parser.add_argument("--arm-ack", default="")
    parser.add_argument("--max-order-quote", default="25.00")
    parser.add_argument("--max-open-orders", type=int, default=4)
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    report = build_phase_c42_final_pre_live_autonomy_bridge_report(
        cfg=cfg,
        ticker=args.ticker,
        live_orders_snapshot=_load_snapshot(args.live_orders_snapshot),
        allow_coinbase_poll=bool(args.allow_coinbase_poll),
        coinbase_client=None,
        risk_dir=args.risk_dir,
        order_store_path=args.order_store,
        order_events_path=args.order_events,
        require_controlled_coinbase_poll=not bool(args.no_require_controlled_poll),
        arm_ack=args.arm_ack,
        autonomous_mode=args.autonomous_mode,
        max_order_quote=args.max_order_quote,
        max_open_orders=args.max_open_orders,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    assessment = report.get("assessment", {})
    c41 = report.get("c41_summary", {})
    print("Phase-C C.4.2 final pre-live autonomy bridge")
    print("================================================")
    print("config_ok:", report.get("config_ok"))
    print("status:", report.get("status"))
    print("selected_ticker:", report.get("selected_ticker"))
    print("ready_to_arm_autonomous_small_live:", report.get("ready_to_arm_autonomous_small_live"))
    print("can_arm_autonomous_now:", report.get("can_arm_autonomous_now"))
    print("actual_coinbase_submit_currently_enabled:", report.get("actual_coinbase_submit_currently_enabled"))
    print("live_submission_attempted_by_this_tool:", report.get("live_submission_attempted_by_this_tool"))
    print("live_order_submitted:", report.get("live_order_submitted"))
    print("cancel_attempted_by_this_tool:", report.get("cancel_attempted_by_this_tool"))
    print("cancel_submitted:", report.get("cancel_submitted"))
    print()
    print("Assessment blockers:", json.dumps(assessment.get("blockers", []), ensure_ascii=False))
    print("Assessment warnings:", json.dumps(assessment.get("warnings", []), ensure_ascii=False))
    print("Runtime readiness:", json.dumps(assessment.get("runtime_readiness_summary", {}), ensure_ascii=False))
    print("Limits:", json.dumps(assessment.get("limits", {}), ensure_ascii=False))
    print("Current config:", json.dumps(assessment.get("current_config", {}), ensure_ascii=False))
    print("C.4.1 summary:", json.dumps(c41, ensure_ascii=False))
    print()
    print("Autonomous mode required for later:", C42_AUTONOMOUS_MODE_NAME)
    print("Human arm ack, alleen voor later final-live:", C42_FINAL_ARM_ACK)
    print("Safety: C.4.2 wijzigt geen .env, submit niet, cancelt niet. Max 25 USDC/order en max 4 open orders blijven harde grenzen voor de eerste autonomous small-live fase.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
