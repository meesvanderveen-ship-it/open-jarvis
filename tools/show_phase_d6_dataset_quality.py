#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_dataset_quality import (  # noqa: E402
    build_phase_d6_dataset_quality_report,
    write_dataset_quality_report,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.6 research-only dataset quality report for local cached/fixture candles. No Coinbase calls."
    )
    parser.add_argument("--candles", required=True, help="Local normalized D.6 candle JSON path")
    parser.add_argument("--as-of", default="", help="Optional ISO timestamp for stale-candle warning checks")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="", help="Optional explicit JSON report output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_dataset_quality_report(
        candles_path=args.candles,
        as_of=args.as_of or None,
    )
    if args.output:
        write_dataset_quality_report(report, args.output)
    if args.json or not args.output:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
