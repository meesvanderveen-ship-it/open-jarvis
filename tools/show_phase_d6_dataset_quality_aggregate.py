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

from bot.phase_d6_dataset_quality_aggregate import (  # noqa: E402
    build_phase_d6_dataset_quality_aggregate_report,
    write_json_aggregate,
    write_markdown_aggregate,
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
        description="D.6 research-only dataset quality aggregate from local cached/fixture candles. No Coinbase calls."
    )
    parser.add_argument("--candles", action="append", required=True, help="Comma-separated or repeatable candle JSON path")
    parser.add_argument("--as-of", default="", help="Optional ISO timestamp for stale-candle warning checks")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="", help="Optional JSON aggregate output path")
    parser.add_argument("--markdown-output", default="", help="Optional Markdown aggregate output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_phase_d6_dataset_quality_aggregate_report(
        candle_paths=_split_csv(args.candles),
        as_of=args.as_of or None,
    )
    if args.output:
        write_json_aggregate(report, args.output)
    if args.markdown_output:
        write_markdown_aggregate(report, args.markdown_output)
    if args.json or not args.output:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
