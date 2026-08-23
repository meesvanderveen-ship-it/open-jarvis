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

from bot.phase_d6_baseline_report_bundle import (  # noqa: E402
    build_phase_d6_baseline_report_bundle,
    write_json_bundle,
    write_markdown_bundle,
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
        description="D.6 research-only baseline report bundle from local cached/fixture candles. No Coinbase calls."
    )
    parser.add_argument("--candles", action="append", required=True, help="Comma-separated or repeatable local candle JSON path")
    parser.add_argument("--baseline", action="append", default=[], help="Comma-separated or repeatable baseline list")
    parser.add_argument("--initial-quote", default="1000")
    parser.add_argument("--fee-pct", default="0.0040")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="", help="Optional JSON report output path")
    parser.add_argument("--markdown-output", default="", help="Optional Markdown summary output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle = build_phase_d6_baseline_report_bundle(
        candle_paths=_split_csv(args.candles),
        baselines=_split_csv(args.baseline) or None,
        initial_quote=args.initial_quote,
        fee_pct=args.fee_pct,
    )
    if args.output:
        write_json_bundle(bundle, args.output)
    if args.markdown_output:
        write_markdown_bundle(bundle, args.markdown_output)
    if args.json or not args.output:
        print(json.dumps(bundle, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
