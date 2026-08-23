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
from bot.phase_d3_local_position_recovery import (
    PHASE_D3_LOCAL_POSITION_RECOVERY_ACK,
    build_phase_d3_local_position_recovery_report,
)
from bot.state_store import StateStore


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview-only or controlled local D.3 position recovery for open-exit hold mismatch."
    )
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--client-order-id", required=True)
    parser.add_argument("--exchange-order-id", required=True)
    parser.add_argument("--linked-position-id", required=True)
    parser.add_argument("--position-size-base", required=True)
    parser.add_argument("--reserved-base-open-exit-orders", required=True)
    parser.add_argument("--bot-managed-base", required=True)
    parser.add_argument("--order-store", default="state/open_orders.json")
    parser.add_argument("--order-log-path", default="logs/order_events.jsonl")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--recovery-ack", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d3_local_position_recovery_report(
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
        linked_position_id=args.linked_position_id,
        position_size_base=args.position_size_base,
        reserved_base_open_exit_orders=args.reserved_base_open_exit_orders,
        bot_managed_base=args.bot_managed_base,
        apply=bool(args.apply),
        recovery_ack=args.recovery_ack,
        order_store=OrderStore(path=args.order_store, log_path=args.order_log_path),
        state_store=StateStore(),
    )
    report["required_recovery_ack"] = PHASE_D3_LOCAL_POSITION_RECOVERY_ACK
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print("D.3 local position recovery")
        print("status:", report.get("status"))
        print("suggested_action:", report.get("suggested_action"))
        print("blockers:", report.get("blockers"))
        print("proposed_position_updates:")
        for key, value in (report.get("proposed_position_updates") or {}).items():
            print(f"  - {key}: {value}")
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
