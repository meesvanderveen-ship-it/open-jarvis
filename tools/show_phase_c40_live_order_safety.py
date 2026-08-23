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
from bot.phase_c40_live_order_safety_layer import build_phase_c40_live_order_safety_report


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
    parser = argparse.ArgumentParser(description="Phase C.4.0 live order safety layer monitor/cancel/expiry scaffold")
    parser.add_argument("--ticker", default="", help="Optionele tickerfilter, bijv. BTC-USDC")
    parser.add_argument("--json", action="store_true", help="Print volledig JSON rapport")
    parser.add_argument("--live-orders-snapshot", default=None, help="Pad naar JSON snapshot met live orders; geen Coinbase call")
    parser.add_argument("--allow-coinbase-poll", action="store_true", help="Alleen voor latere handmatige diagnose; vereist code die een client doorgeeft. Deze CLI geeft geen client door.")
    parser.add_argument("--order-store", default="state/open_orders.json")
    parser.add_argument("--order-events", default="logs/order_events.jsonl")
    args = parser.parse_args()

    cfg = BotConfig()
    cfg.validate()
    report = build_phase_c40_live_order_safety_report(
        cfg=cfg,
        ticker=args.ticker or None,
        live_orders_snapshot=_load_snapshot(args.live_orders_snapshot),
        allow_coinbase_poll=bool(args.allow_coinbase_poll),
        coinbase_client=None,
        order_store_path=args.order_store,
        order_events_path=args.order_events,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    safety = report.get("safety_assessment", {})
    counts = safety.get("counts", {})
    print("Phase-C C.4.0 live order safety layer")
    print("=======================================")
    print("config_ok:", report.get("config_ok"))
    print("status:", report.get("status"))
    print("selected_ticker:", report.get("selected_ticker"))
    print("actual_coinbase_submit_currently_enabled:", report.get("actual_coinbase_submit_currently_enabled"))
    print("coinbase_call_attempted:", report.get("coinbase_poll", {}).get("coinbase_call_attempted"))
    print("coinbase_call_succeeded:", report.get("coinbase_poll", {}).get("coinbase_call_succeeded"))
    print("cancel_attempted_by_this_tool:", report.get("dry_run_cancel_plan", {}).get("cancel_attempted_by_this_tool"))
    print("cancel_submitted:", report.get("dry_run_cancel_plan", {}).get("cancel_submitted"))
    print()
    print("Counts:", json.dumps(counts, ensure_ascii=False))
    print("Blockers:", json.dumps(safety.get("blockers", []), ensure_ascii=False))
    print("Warnings:", json.dumps(safety.get("warnings", []), ensure_ascii=False))
    if safety.get("recommendations"):
        print("Recommendations:")
        for rec in safety.get("recommendations", []):
            print("-", rec.get("ticker"), rec.get("side"), rec.get("recommendation"), rec.get("reasons"))
    print()
    print("Safety: C.4.0 is read-only. Geen submit, geen cancel-call, geen .env-wijziging, geen live exits, geen follower lifecycle.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
