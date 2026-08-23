#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.protective_position_watcher import build_protective_position_watcher_report_from_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Show preview-only protective position watcher status.")
    parser.add_argument("--positions-file", default="state/positions.json")
    parser.add_argument("--open-orders-file", default="state/open_orders.json")
    parser.add_argument("--market-file", default="")
    parser.add_argument("--d2-plans-file", default="state/phase_d2_position_executor_plans.json")
    parser.add_argument("--allow-coinbase-read-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = build_protective_position_watcher_report_from_files(
        positions_path=args.positions_file,
        open_orders_path=args.open_orders_file,
        market_path=args.market_file or None,
        d2_plans_path=args.d2_plans_file or None,
        allow_coinbase_read_only=args.allow_coinbase_read_only,
    )
    print(json.dumps(report, indent=2 if not args.json else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
