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
from bot.phase_c44_poll_to_apply_closeout import load_live_order_snapshots_from_file
from bot.phase_c45_live_fill_pilot import build_phase_c45_live_fill_pilot_report
from bot.state_store import StateStore


def _build_coinbase_client():
    from bot.coinbase_client import CoinbaseClient
    return CoinbaseClient()


def main() -> int:
    p = argparse.ArgumentParser(description="C.4.5 controlled live fill pilot for an existing C.4.3 live entry order")
    p.add_argument("--ticker", default="BTC-USDC")
    p.add_argument("--order-store", default="state/open_orders.json")
    p.add_argument("--order-events", default="logs/order_events.jsonl")
    p.add_argument("--snapshot-file", default="", help="Optional fake/read-only snapshot JSON file; avoids Coinbase call.")
    p.add_argument("--allow-coinbase-poll", action="store_true", help="Allow read-only Coinbase order/fill poll. No submit/cancel/replace.")
    p.add_argument("--apply-fill", action="store_true", help="Apply filled/partial evidence to local position lifecycle. Requires exact ACK.")
    p.add_argument("--fill-apply-ack", default="", help="Must equal I_UNDERSTAND_AND_APPROVE_C45_FILL_TO_POSITION_APPLY when --apply-fill is used.")
    p.add_argument("--build-d2-plan", action="store_true", help="After fill apply, build D.2 position executor plan. No SELL.")
    p.add_argument("--persist-d2-plan", action="store_true", help="Persist D.2 plan if ready. No SELL.")
    p.add_argument("--build-d3-preview", action="store_true", help="After D.2/fill, build D.3 preview with submit_live=False.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    cfg = BotConfig()
    cfg.validate()
    store = OrderStore(path=args.order_store, log_path=args.order_events, max_orders=max(200, int(getattr(cfg, "order_store_max_records", 2000))))
    snapshots = load_live_order_snapshots_from_file(args.snapshot_file) if args.snapshot_file else None
    client = _build_coinbase_client() if args.allow_coinbase_poll and not snapshots else None
    report = build_phase_c45_live_fill_pilot_report(
        cfg=cfg,
        ticker=args.ticker,
        order_store=store,
        state_store=StateStore(),
        coinbase_client=client,
        live_orders_snapshot=snapshots,
        allow_coinbase_poll=args.allow_coinbase_poll,
        apply_fill=args.apply_fill,
        fill_apply_ack=args.fill_apply_ack,
        build_d2_plan=args.build_d2_plan,
        persist_d2_plan=args.persist_d2_plan,
        build_d3_preview=args.build_d3_preview,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
        return 0 if not report.get("blockers") and not ((report.get("c44_report") or {}).get("preview_report") or {}).get("errors") else 2

    print("C.4.5 controlled live fill pilot")
    print("=================================")
    print(f"status: {report.get('status')}")
    print(f"ticker: {report.get('ticker')}")
    print(f"local_open_c43_before: {report.get('local_open_c43_before')}")
    print(f"local_open_c43_after: {report.get('local_open_c43_after')}")
    print(f"fill_apply_summary: {report.get('fill_apply_summary')}")
    print(f"blockers: {report.get('blockers')}")
    print("Safety: no Coinbase submit/cancel/replace, no live SELL. Fill apply requires explicit C.4.5 ACK.")
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
