#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.phase_c45_maker_price_scout import build_phase_c45_maker_price_scout_report


def _build_coinbase_client():
    from bot.coinbase_client import CoinbaseClient
    return CoinbaseClient()


def main() -> int:
    p = argparse.ArgumentParser(description="Read-only C.4.5 maker-price scout for one controlled BTC-USDC fill pilot")
    p.add_argument("--ticker", default="BTC-USDC")
    p.add_argument("--quote-size", default="10.00")
    p.add_argument("--bid-ticks-below", type=int, default=0, help="0 joins best bid; 1 places one price increment below best bid.")
    p.add_argument("--do-not-join-best-bid", action="store_true", help="Use best_bid - 1 tick before applying --bid-ticks-below.")
    p.add_argument("--max-spread-pct", default="0.20", help="Block when current spread pct exceeds this value. Use 0 to disable.")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    cfg = BotConfig()
    cfg.validate()
    report = build_phase_c45_maker_price_scout_report(
        cfg=cfg,
        ticker=args.ticker,
        coinbase_client=_build_coinbase_client(),
        quote_size=args.quote_size,
        join_best_bid=not args.do_not_join_best_bid,
        bid_ticks_below=args.bid_ticks_below,
        max_spread_pct=args.max_spread_pct,
    )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        mp = report.get("maker_price") or {}
        tob = report.get("top_of_book") or {}
        print("C.4.5 maker price scout")
        print("========================")
        print(f"status: {report.get('status')}")
        print(f"ticker: {report.get('ticker')}")
        print(f"best_bid: {tob.get('best_bid')} | best_ask: {tob.get('best_ask')} | spread_pct: {tob.get('spread_pct')}")
        print(f"recommended limit_price: {mp.get('limit_price')}")
        print(f"estimated_base_size: {mp.get('estimated_base_size')}")
        print(f"blockers: {report.get('blockers')}")
        print("\nPreview command:")
        print((report.get("commands") or {}).get("preview"))
        print("\nSubmit command:")
        print((report.get("commands") or {}).get("submit_live"))
        print("\nPost-submit C.4.5 poll:")
        print((report.get("commands") or {}).get("c45_read_only_poll"))
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
