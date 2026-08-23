#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.config import BotConfig  # noqa: E402
from bot.order_store import OrderStore  # noqa: E402
from bot.phase_c43_lifecycle_governance import build_phase_c43_lifecycle_governance_report  # noqa: E402


def _is_c43_live_entry_order(order: Dict[str, Any]) -> bool:
    return (
        str(order.get("side") or "").upper() == "BUY"
        and str(order.get("mode") or "").lower() == "live"
        and str(order.get("execution_action") or "").lower() == "place_limit_buy"
        and bool(order.get("opened_via_phase_c43") or str(order.get("source_mode") or "").lower() == "autonomous_small_live")
    )


def _local_orders(store: OrderStore, ticker: Optional[str]) -> List[Dict[str, Any]]:
    selected = str(ticker or "").strip().upper()
    out = []
    for order in store.open_entry_orders(ticker=selected or None):
        if _is_c43_live_entry_order(order):
            out.append(order)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Show C.4.4.2 lifecycle poll/apply governance without calling Coinbase or mutating state.")
    ap.add_argument("--ticker", default="", help="Optional ticker filter, for example BTC-USDC. Default scans all local C.4.3 open entry orders.")
    ap.add_argument("--order-store", default="state/open_orders.json")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fail-on-blocker", action="store_true")
    args = ap.parse_args()

    cfg = BotConfig()
    store = OrderStore(path=args.order_store, log_path=getattr(cfg, "phase_c43_lifecycle_order_events_path", "logs/order_events.jsonl"))
    orders = _local_orders(store, args.ticker or None)
    report = build_phase_c43_lifecycle_governance_report(
        cfg=cfg,
        local_open_c43_orders=orders,
        ticker=args.ticker,
        cycle_type="manual",
        source="tools/show_phase_c43_lifecycle_governance.py",
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print("C.4.4.2 lifecycle poll/apply governance")
        print("===========================================")
        print(f"Status: {report.get('status')}")
        print(f"Open C.4.3 orders: {report.get('local_open_c43_orders', {}).get('count', 0)}")
        eff = report.get("effective_flags", {})
        print("Effective flags:")
        for key in ("allow_coinbase_poll", "apply_local", "build_d2_plan", "persist_d2_plan", "build_d3_preview"):
            print(f"  {key}: {eff.get(key)}")
        blockers = report.get("blockers") or []
        warnings = report.get("warnings") or []
        if blockers:
            print("Blockers:")
            for item in blockers:
                print(f"  - {item}")
        if warnings:
            print("Warnings:")
            for item in warnings:
                print(f"  - {item}")
        print("Decisions:")
        for item in report.get("decisions") or []:
            print(f"  - {item}")

    return 2 if args.fail_on_blocker and report.get("blockers") else 0


if __name__ == "__main__":
    raise SystemExit(main())
