#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d45_historical_exit_operations_report import build_report_from_files


def _parse_now(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Local-only historical D.45 exit operations report. No Coinbase calls, no state writes."
    )
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--active-client-order-id", default="phased4-BTCUSDC-TP1-repl-bc3330fe-20260529064443")
    parser.add_argument("--active-exchange-order-id", default="6f6fa436-f5b9-4df5-bb23-ddf35a27a56a")
    parser.add_argument("--linked-position-id", default="76310097-849e-481c-b587-ba44bc3330fe")
    parser.add_argument("--old-client-order-id", default="")
    parser.add_argument("--old-exchange-order-id", default="")
    parser.add_argument("--orders-file", default=str(PROJECT_ROOT / "state" / "open_orders.json"))
    parser.add_argument("--positions-file", default=str(PROJECT_ROOT / "state" / "positions.json"))
    parser.add_argument("--event-log", default="")
    parser.add_argument("--market-mid", default="")
    parser.add_argument("--now", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report_from_files(
        orders_file=args.orders_file,
        positions_file=args.positions_file,
        ticker=args.ticker,
        active_client_order_id=args.active_client_order_id,
        active_exchange_order_id=args.active_exchange_order_id,
        linked_position_id=args.linked_position_id,
        old_client_order_id=args.old_client_order_id,
        old_exchange_order_id=args.old_exchange_order_id,
        market_mid=args.market_mid,
        event_log_path=args.event_log,
        now=_parse_now(args.now),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 2 if report.get("status") == "d45_historical_exit_operations_blocked_p0" else 0


if __name__ == "__main__":
    raise SystemExit(main())
