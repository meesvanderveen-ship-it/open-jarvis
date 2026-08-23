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

from bot.phase_d6_cost_aware_baseline_bundle import (  # noqa: E402
    build_phase_d6_cost_aware_baseline_bundle,
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
        description="D.6 research-only cost-aware baseline bundle from local cached/fixture candles. No Coinbase calls."
    )
    parser.add_argument("--candles", action="append", required=True, help="Comma-separated or repeatable local candle JSON path")
    parser.add_argument("--cost-scenario", action="append", default=[], help="Comma-separated or repeatable cost scenario list")
    parser.add_argument("--split-mode", choices=["holdout", "rolling", "expanding"], default="holdout")
    parser.add_argument("--train-count", type=int, default=210)
    parser.add_argument("--validation-count", type=int, default=70)
    parser.add_argument("--test-count", type=int, default=70)
    parser.add_argument("--step-count", type=int, default=70)
    parser.add_argument("--max-splits", type=int, default=12)
    parser.add_argument("--initial-quote", default="1000")
    parser.add_argument("--allow-quality-warnings", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--output", default="", help="Optional JSON report output path")
    parser.add_argument("--markdown-output", default="", help="Optional Markdown summary output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bundle = build_phase_d6_cost_aware_baseline_bundle(
        candle_paths=_split_csv(args.candles),
        cost_scenarios=_split_csv(args.cost_scenario) or None,
        split_mode=args.split_mode,
        train_count=args.train_count,
        validation_count=args.validation_count,
        test_count=args.test_count,
        step_count=args.step_count,
        max_splits=args.max_splits,
        initial_quote=args.initial_quote,
        require_quality_ready=not args.allow_quality_warnings,
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
