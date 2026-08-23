#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_split_aware_baseline import (  # noqa: E402
    build_phase_d6_split_aware_baseline_report,
    write_split_aware_baseline_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.6 research-only split-aware baseline report using local cached/fixture candles. No Coinbase calls."
    )
    parser.add_argument("--candles", required=True, help="Local normalized D.6 candle JSON path")
    parser.add_argument("--split-mode", choices=["holdout", "rolling", "expanding"], default="holdout")
    parser.add_argument("--baseline", choices=["buy_hold"], default="buy_hold")
    parser.add_argument("--train-count", type=int, default=210)
    parser.add_argument("--validation-count", type=int, default=70)
    parser.add_argument("--test-count", type=int, default=70)
    parser.add_argument("--step-count", type=int, default=70)
    parser.add_argument("--max-splits", type=int, default=12)
    parser.add_argument("--initial-quote", default="1000")
    parser.add_argument("--fee-pct", default="0.0040")
    parser.add_argument("--allow-quality-warnings", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="", help="Optional explicit JSON report output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_split_aware_baseline_report(
        candles_path=args.candles,
        split_mode=args.split_mode,
        baseline=args.baseline,
        train_count=args.train_count,
        validation_count=args.validation_count,
        test_count=args.test_count,
        step_count=args.step_count,
        max_splits=args.max_splits,
        initial_quote=args.initial_quote,
        fee_pct=args.fee_pct,
        require_quality_ready=not args.allow_quality_warnings,
    )
    if args.output:
        write_split_aware_baseline_report(report, args.output)
    if args.json or not args.output:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
