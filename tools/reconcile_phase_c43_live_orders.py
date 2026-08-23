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
from bot.phase_c43_lifecycle_orchestrator import build_phase_c43_lifecycle_orchestrator_report
from bot.state_store import StateStore


def _build_coinbase_client():
    from bot.coinbase_client import CoinbaseClient
    return CoinbaseClient()


def main() -> int:
    p = argparse.ArgumentParser(description="C.4.4/D.3.3 lifecycle orchestrator v1: reconcile C.4.3 live entry orders with read-only Coinbase snapshots")
    p.add_argument("--ticker", default="BTC-USDC")
    p.add_argument("--order-store", default="state/open_orders.json")
    p.add_argument("--order-events", default="logs/order_events.jsonl")
    p.add_argument("--json", action="store_true")
    p.add_argument("--allow-coinbase-poll", action="store_true", help="Read-only Coinbase get_order/fills calls for local C.4.3 orders. No submit/cancel.")
    p.add_argument("--apply-local", action="store_true", help="Apply local OrderStore/StateStore reconciliation only. No Coinbase submit/cancel and no live SELL.")
    p.add_argument("--build-d2-plan", action="store_true", help="After a filled entry has opened a position, build D.2 plan/preview.")
    p.add_argument("--persist-d2-plan", action="store_true", help="Persist D.2 plan only if ready. Does not submit SELL.")
    p.add_argument("--build-d3-preview", action="store_true", help="Build D.3 controlled exit preview with submit_live=False.")
    args = p.parse_args()

    cfg = BotConfig()
    cfg.validate()
    store = OrderStore(path=args.order_store, log_path=args.order_events, max_orders=max(200, int(getattr(cfg, "order_store_max_records", 2000))))
    client = _build_coinbase_client() if args.allow_coinbase_poll else None
    report = build_phase_c43_lifecycle_orchestrator_report(
        cfg=cfg,
        ticker=args.ticker,
        order_store=store,
        state_store=StateStore(),
        coinbase_client=client,
        allow_coinbase_poll=args.allow_coinbase_poll,
        apply_local=args.apply_local,
        build_d2_plan=args.build_d2_plan,
        persist_d2_plan=args.persist_d2_plan,
        build_d3_preview=args.build_d3_preview,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if not report.get("errors") else 2

    print("C.4.4 / D.3.3 lifecycle orchestrator v1")
    print("========================================")
    print(f"status: {report.get('status')}")
    print(f"mode: {report.get('mode')}")
    print(f"ticker: {report.get('ticker')}")
    print(f"local_c43_open_orders_seen: {report.get('local_c43_open_orders_seen')}")
    print(f"coinbase_call_attempted: {report.get('coinbase_call_attempted')}")
    print(f"coinbase_call_succeeded: {report.get('coinbase_call_succeeded')}")
    print(f"snapshot_count: {report.get('snapshot_count')}")
    print(f"proposed_actions: {len(report.get('proposed_actions') or [])}")
    print(f"applied_actions: {len(report.get('applied_actions') or [])}")
    print(f"d2_reports: {len(report.get('d2_reports') or [])}")
    print(f"d3_previews: {len(report.get('d3_previews') or [])}")
    print(f"errors: {len(report.get('errors') or [])}")
    for action in report.get("proposed_actions") or []:
        print(f"- {action.get('ticker')} {action.get('client_order_id')} local={action.get('local_status')} coinbase={action.get('coinbase_status')} action={action.get('action')} proposed={action.get('proposed_local_status')}")
    print()
    print("Safety: preview is read-only by default. --apply-local only updates local lifecycle/positions after fill evidence. No Coinbase submit/cancel. No live SELL/exits.")
    return 0 if not report.get("errors") else 2


if __name__ == "__main__":
    raise SystemExit(main())
