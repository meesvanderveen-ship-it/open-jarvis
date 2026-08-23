#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_binance_public_klines import (  # noqa: E402
    BinanceRateLimitPolicy,
    build_binance_klines_plan,
    execute_binance_klines_fetch,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="D.6 Binance public klines diagnostic fetch. Public market data only.")
    parser.add_argument("--mapped-coinbase-product", default="BTC-USDC")
    parser.add_argument("--symbol", default="")
    parser.add_argument("--timeframe", default="4H")
    parser.add_argument("--start", type=int, required=True)
    parser.add_argument("--end-exclusive", type=int, required=True)
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--candidate-root", default="/tmp/d6_binance_public_klines_v21")
    parser.add_argument("--run-id", default="binance-btcusdc-4h-gap-reference-v21")
    parser.add_argument("--max-requests-per-run", type=int, default=1)
    parser.add_argument("--min-delay-seconds", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--retry-budget", type=int, default=1)
    parser.add_argument("--fetch", action="store_true", help="Execute one bounded public kline request.")
    args = parser.parse_args()

    policy = BinanceRateLimitPolicy(
        max_requests_per_run=args.max_requests_per_run,
        min_delay_seconds=args.min_delay_seconds,
        max_retries_per_request=args.max_retries,
        retry_budget_total=args.retry_budget,
    )
    plan = build_binance_klines_plan(
        mapped_coinbase_product=args.mapped_coinbase_product,
        symbol=args.symbol or None,
        timeframe=args.timeframe,
        start=args.start,
        end_exclusive=args.end_exclusive,
        candidate_root=args.candidate_root,
        run_id=args.run_id,
        limit=args.limit,
        policy=policy,
    )
    result = execute_binance_klines_fetch(plan=plan) if args.fetch else plan
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if not result.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
