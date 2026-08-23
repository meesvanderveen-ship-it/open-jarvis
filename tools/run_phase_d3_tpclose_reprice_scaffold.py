#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.coinbase_client import CoinbaseClient
from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.phase_d3_tpclose_reprice_scaffold import build_phase_d3_tpclose_reprice_scaffold_report
from bot.state_store import StateStore


def _load_json(path: str):
    if not path:
        return None
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def main() -> int:
    p = argparse.ArgumentParser(description="Exact TP_CLOSE cancel/replace/reprice scaffold. Dry-run by default.")
    p.add_argument("--ticker", default="BTC-USDC")
    p.add_argument("--client-order-id", required=True)
    p.add_argument("--exchange-order-id", required=True)
    p.add_argument("--linked-position-id", required=True)
    p.add_argument("--new-limit-price", required=True)
    p.add_argument("--old-snapshot-fixture", default="")
    p.add_argument("--base-increment", default="0.00000001")
    p.add_argument("--base-min-size", default="0.00000001")
    p.add_argument("--quote-min-size", default="1")
    p.add_argument("--price-increment", default="0.01")
    p.add_argument("--confirm-label", default="")
    p.add_argument("--submit-live", action="store_true")
    p.add_argument("--reprice-ack", default="")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    report = build_phase_d3_tpclose_reprice_scaffold_report(
        cfg=BotConfig(),
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
        linked_position_id=args.linked_position_id,
        new_limit_price=args.new_limit_price,
        state_store=StateStore(),
        order_store=OrderStore(),
        coinbase_client=CoinbaseClient() if args.submit_live else None,
        old_snapshot=_load_json(args.old_snapshot_fixture),
        base_increment=args.base_increment,
        base_min_size=args.base_min_size,
        quote_min_size=args.quote_min_size,
        price_increment=args.price_increment,
        submit_live=bool(args.submit_live),
        reprice_ack=args.reprice_ack,
        confirm_label=args.confirm_label,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
