#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.order_store import OrderStore
from bot.phase_d3_cancel_closeout_local_reconcile import (
    build_phase_d3_cancel_closeout_local_reconcile_report,
)
from bot.state_store import StateStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview/apply local-only D.3 cancelled TP1 closeout.")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--client-order-id", required=True)
    parser.add_argument("--exchange-order-id", required=True)
    parser.add_argument("--linked-position-id", required=True)
    parser.add_argument("--evidence-hash", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--ack", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d3_cancel_closeout_local_reconcile_report(
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
        linked_position_id=args.linked_position_id,
        evidence_hash=args.evidence_hash,
        order_store=OrderStore(),
        state_store=StateStore(),
        apply=bool(args.apply),
        ack=args.ack,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
