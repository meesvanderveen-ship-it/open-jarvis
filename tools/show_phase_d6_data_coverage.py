#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_data_coverage import (  # noqa: E402
    assert_research_output_path,
    build_phase_d6_data_coverage_report,
)


def _split_csv(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for item in str(raw or "").split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.6 research-only data coverage inventory. No Coinbase calls and no trading-state writes."
    )
    parser.add_argument("--as-of", required=True, help="Deterministic cutoff date, e.g. 2026-05-29")
    parser.add_argument("--tickers", action="append", default=[], help="Comma-separated or repeatable ticker list")
    parser.add_argument("--timeframes", action="append", default=[], help="Comma-separated or repeatable timeframe list")
    parser.add_argument("--years", action="append", default=[], help="Comma-separated or repeatable year windows, e.g. 3,5")
    parser.add_argument("--json", action="store_true", help="Emit JSON. Default also emits JSON for machine-safe output.")
    parser.add_argument("--output", default="", help="Optional explicit research/report output path. Refuses state/ paths.")
    return parser.parse_args()


def build_report(args: argparse.Namespace) -> dict:
    return build_phase_d6_data_coverage_report(
        as_of=args.as_of,
        tickers=_split_csv(args.tickers) or None,
        timeframes=_split_csv(args.timeframes) or None,
        years=_split_csv(args.years) or None,
    )


def main() -> int:
    args = parse_args()
    report = build_report(args)
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False)
    if args.output:
        output_path = assert_research_output_path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
