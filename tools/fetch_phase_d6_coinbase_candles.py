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

from bot.phase_d6_coinbase_candle_ingest import (  # noqa: E402
    DEFAULT_OUTPUT_ROOT,
    build_phase_d6_coinbase_candle_ingest_report,
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
        description="D.6 research-only Coinbase candle ingest. Default is dry-run; fetch requires --fetch and --max-chunks."
    )
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--tickers", action="append", default=[])
    parser.add_argument("--timeframes", action="append", default=[])
    parser.add_argument("--years", action="append", default=[])
    parser.add_argument("--max-chunks", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true", help="Explicit dry-run. This is also the default.")
    parser.add_argument("--fetch", action="store_true", help="Execute bounded read-only candle fetches.")
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--manifest-output", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.fetch and args.dry_run:
        raise SystemExit("--fetch and --dry-run are mutually exclusive")

    client = None
    if args.fetch:
        from coinbase_client import CoinbaseClient  # Imported only for explicit fetch mode.

        client = CoinbaseClient()

    report = build_phase_d6_coinbase_candle_ingest_report(
        as_of=args.as_of,
        tickers=_split_csv(args.tickers) or None,
        timeframes=_split_csv(args.timeframes) or None,
        years=_split_csv(args.years) or None,
        max_chunks=args.max_chunks,
        fetch=bool(args.fetch),
        client=client,
        output_root=args.output_root,
        manifest_output=args.manifest_output or None,
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
