#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d3_reservation_repair_preview import (
    D3_RESERVATION_DRIFT_REPAIR_ACK,
    build_phase_d3_reservation_repair_preview_from_files,
)


DEFAULT_TICKER = "BTC-USDC"
DEFAULT_CLIENT_ORDER_ID = "phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000"
DEFAULT_EXCHANGE_ORDER_ID = "daa5ef77-9967-4fb0-b0c7-4f7c0680b512"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or guarded apply for D.3 reservation drift. No Coinbase calls and no live action."
    )
    parser.add_argument("--ticker", default=DEFAULT_TICKER)
    parser.add_argument("--client-order-id", default=DEFAULT_CLIENT_ORDER_ID)
    parser.add_argument("--exchange-order-id", default=DEFAULT_EXCHANGE_ORDER_ID)
    parser.add_argument("--orders-file", default=str(PROJECT_ROOT / "state" / "open_orders.json"))
    parser.add_argument("--positions-file", default=str(PROJECT_ROOT / "state" / "positions.json"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--repair-ack", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_report(args: argparse.Namespace):
    return build_phase_d3_reservation_repair_preview_from_files(
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
        orders_file=args.orders_file,
        positions_file=args.positions_file,
        apply=bool(args.apply),
        repair_ack=args.repair_ack,
    )


def main() -> int:
    args = parse_args()
    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        print("D.3 reservation drift repair")
        print("status:", report.get("status"))
        print("suggested_action:", report.get("suggested_action"))
        print("blockers:", report.get("blockers"))
        print("current_reserved_base:", report.get("current_reserved_base"))
        print("required_reserved_base:", report.get("required_reserved_base"))
        print("proposed_reserved_base_after:", report.get("proposed_reserved_base_after"))
        print("available_base_after_reservations_after:", report.get("available_base_after_reservations_after"))
        print("required_ack:", D3_RESERVATION_DRIFT_REPAIR_ACK)
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
