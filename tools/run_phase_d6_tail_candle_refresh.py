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

from bot.phase_d6_tail_candle_refresh import build_tail_refresh_plan, execute_tail_refresh, merge_tail_refresh_result  # noqa: E402


def _split_csv(values: List[str]) -> List[str]:
    out: List[str] = []
    for raw in values:
        for item in str(raw or "").split(","):
            item = item.strip()
            if item:
                out.append(item)
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="D.6 tail-aware research candle refresh. Dry-run by default.")
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--tickers", action="append", default=[])
    parser.add_argument("--timeframes", action="append", default=[])
    parser.add_argument("--max-chunks", type=int, required=True)
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--merge", action="store_true", help="Merge/dedup fetched candidate candles into research_data cache.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.fetch and args.dry_run:
        raise SystemExit("--fetch and --dry-run are mutually exclusive")
    plan = build_tail_refresh_plan(
        as_of=args.as_of,
        tickers=_split_csv(args.tickers),
        timeframes=_split_csv(args.timeframes),
        max_chunks=args.max_chunks,
        output_root=args.candidate_root,
    )
    report = plan
    if args.fetch:
        from coinbase_client import CoinbaseClient  # Imported only for explicit fetch mode.

        report = execute_tail_refresh(plan=plan, client=CoinbaseClient())
        if args.merge:
            report = {
                "fetch_result": report,
                "merge_result": merge_tail_refresh_result(fetch_result=report),
            }
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
