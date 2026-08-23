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
from bot.phase_c41_pre_live_readiness import build_phase_c41_pre_live_readiness_report, C41_EMERGENCY_CANCEL_ACK


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
    parser = argparse.ArgumentParser(description="Phase C.4.1 combined pre-live readiness, controlled poll and emergency-cancel hardlock")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--live-orders-snapshot", default=None, help="Pad naar JSON snapshot met live orders; geen Coinbase call")
    parser.add_argument("--allow-coinbase-poll", action="store_true", help="Alleen voor latere diagnose; deze CLI geeft geen Coinbase client door")
    parser.add_argument("--risk-dir", default=None, help="Map met deterministic live-risk JSON snapshots")
    parser.add_argument("--order-store", default="state/open_orders.json")
    parser.add_argument("--order-events", default="logs/order_events.jsonl")
    parser.add_argument("--no-require-controlled-poll", action="store_true", help="Alleen voor lokale/snapshot tests; live go/no-go vereist wel controlled poll")
    parser.add_argument("--emergency-cancel-mode", default="dry_run")
    parser.add_argument("--human-cancel-ack", default="")
    parser.add_argument("--cancel-live", action="store_true")
    parser.add_argument("--cancel-order-id", action="append", default=[])
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    report = build_phase_c41_pre_live_readiness_report(
        cfg=cfg,
        ticker=args.ticker,
        live_orders_snapshot=_load_snapshot(args.live_orders_snapshot),
        allow_coinbase_poll=bool(args.allow_coinbase_poll),
        coinbase_client=None,
        risk_dir=args.risk_dir,
        order_store_path=args.order_store,
        order_events_path=args.order_events,
        require_controlled_coinbase_poll=not bool(args.no_require_controlled_poll),
        emergency_cancel_mode=args.emergency_cancel_mode,
        human_cancel_ack=args.human_cancel_ack,
        cancel_live=bool(args.cancel_live),
        cancel_order_ids=args.cancel_order_id,
        cancel_coinbase_client=None,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    readiness = report.get("readiness", {})
    c40 = report.get("c40_summary", {})
    emergency = report.get("emergency_cancel", {})
    print("Phase-C C.4.1 combined pre-live readiness")
    print("===========================================")
    print("config_ok:", report.get("config_ok"))
    print("status:", report.get("status"))
    print("selected_ticker:", report.get("selected_ticker"))
    print("pre_live_ready_no_submit:", report.get("pre_live_ready_no_submit"))
    print("actual_coinbase_submit_currently_enabled:", report.get("actual_coinbase_submit_currently_enabled"))
    print("live_submission_attempted_by_this_tool:", report.get("live_submission_attempted_by_this_tool"))
    print("live_order_submitted:", report.get("live_order_submitted"))
    print("cancel_attempted_by_this_tool:", report.get("cancel_attempted_by_this_tool"))
    print("cancel_submitted:", report.get("cancel_submitted"))
    print()
    print("Readiness blockers:", json.dumps(readiness.get("blockers", []), ensure_ascii=False))
    print("Readiness warnings:", json.dumps(readiness.get("warnings", []), ensure_ascii=False))
    print("Readiness summary:", json.dumps(readiness.get("readiness_summary", {}), ensure_ascii=False))
    print("Risk bridge:", json.dumps(report.get("live_risk_bridge", {}), ensure_ascii=False))
    print("C.4.0 poll/counts:", json.dumps({"coinbase_poll": c40.get("coinbase_poll"), "counts": c40.get("counts")}, ensure_ascii=False))
    print("Emergency cancel hardlock:", json.dumps(emergency.get("hardlock", {}), ensure_ascii=False))
    print()
    print("Human emergency cancel ack, alleen voor latere noodrem:", C41_EMERGENCY_CANCEL_ACK)
    print("Safety: C.4.1 combineert pre-live checks. Standaard geen submit, geen cancel, geen .env-wijziging, geen live exits, geen follower lifecycle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
