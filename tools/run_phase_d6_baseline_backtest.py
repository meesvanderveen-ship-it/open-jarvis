#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_baseline_backtest import (  # noqa: E402
    build_phase_d6_baseline_backtest_report,
    write_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.6 research-only baseline backtest scaffold using cached/fixture candles. No Coinbase calls."
    )
    parser.add_argument("--candles", required=True)
    parser.add_argument("--baseline", choices=["buy_hold", "simple_ma"], default="buy_hold")
    parser.add_argument("--initial-quote", default="1000")
    parser.add_argument("--fee-pct", default="0.0040")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_baseline_backtest_report(
        candles_path=args.candles,
        baseline=args.baseline,
        initial_quote=args.initial_quote,
        fee_pct=args.fee_pct,
    )
    if args.output:
        write_report(report, args.output)
    if args.json or not args.output:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
