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
from bot.phase_c44_poll_to_apply_closeout import build_phase_c44_poll_to_apply_closeout_report, load_live_order_snapshots_from_file
from bot.state_store import StateStore


def _build_coinbase_client():
    from bot.coinbase_client import CoinbaseClient
    return CoinbaseClient()


def main() -> int:
    p = argparse.ArgumentParser(description="C.4.4.4 governed poll-to-apply closeout runner for C.4.3 live entry orders")
    p.add_argument("--ticker", default="BTC-USDC")
    p.add_argument("--order-store", default="state/open_orders.json")
    p.add_argument("--order-events", default="logs/order_events.jsonl")
    p.add_argument("--snapshot-file", default="", help="Optional fake/read-only snapshot JSON file for preview/apply tests; avoids Coinbase call.")
    p.add_argument("--allow-coinbase-poll", action="store_true", help="Allow read-only Coinbase order/fill poll. No submit/cancel/replace.")
    p.add_argument("--apply-local", action="store_true", help="Apply local lifecycle reconciliation if governance permits. No Coinbase mutation.")
    p.add_argument("--allow-fill-apply", action="store_true", help="Allow filled/partial snapshots to flow into fill-to-position logic. Required before D.2/D.3.")
    p.add_argument("--build-d2-plan", action="store_true", help="After fill evidence and apply-local, build D.2 plan. No SELL.")
    p.add_argument("--persist-d2-plan", action="store_true", help="Persist D.2 plan if ready. No SELL.")
    p.add_argument("--build-d3-preview", action="store_true", help="After fill evidence and D.2, build D.3 preview with submit_live=False.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    cfg = BotConfig()
    cfg.validate()
    store = OrderStore(path=args.order_store, log_path=args.order_events, max_orders=max(200, int(getattr(cfg, "order_store_max_records", 2000))))
    snapshots = load_live_order_snapshots_from_file(args.snapshot_file) if args.snapshot_file else None
    client = _build_coinbase_client() if args.allow_coinbase_poll and not snapshots else None
    report = build_phase_c44_poll_to_apply_closeout_report(
        cfg=cfg,
        ticker=args.ticker,
        order_store=store,
        state_store=StateStore(),
        coinbase_client=client,
        live_orders_snapshot=snapshots,
        allow_coinbase_poll=args.allow_coinbase_poll,
        apply_local=args.apply_local,
        build_d2_plan=args.build_d2_plan,
        persist_d2_plan=args.persist_d2_plan,
        build_d3_preview=args.build_d3_preview,
        allow_fill_apply=args.allow_fill_apply,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if not report.get("blockers") and not (report.get("preview_report") or {}).get("errors") else 2

    print("C.4.4.4 poll-to-apply closeout")
    print("================================")
    print(f"status: {report.get('status')}")
    print(f"ticker: {report.get('ticker')}")
    print(f"local_open_c43_before: {report.get('local_open_c43_before')}")
    print(f"local_open_c43_after: {report.get('local_open_c43_after')}")
    print(f"governance: {(report.get('governance_report') or {}).get('status')}")
    print(f"preview_actions: {report.get('action_summary')}")
    print(f"applied_actions: {len(((report.get('apply_report') or {}).get('applied_actions') or []))}")
    print(f"blockers: {report.get('blockers')}")
    print("Safety: no Coinbase submit/cancel/replace, no live SELL. Preview first; apply-local only under governance.")
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
