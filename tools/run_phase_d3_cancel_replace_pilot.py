#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.coinbase_client import CoinbaseClient
from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.phase_d3_cancel_replace_pilot import run_phase_d3_cancel_replace_pilot
from bot.state_store import StateStore


def _load_snapshot_fixture(path: str) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview or run a controlled D.3 cancel/replace pilot.")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--client-order-id", required=True)
    parser.add_argument("--exchange-order-id", required=True)
    parser.add_argument("--linked-position-id", required=True)
    parser.add_argument("--snapshot-fixture", default="")
    parser.add_argument("--allow-coinbase-poll", action="store_true")
    parser.add_argument("--allow-live-cancel", action="store_true")
    parser.add_argument("--allow-live-replace", action="store_true")
    parser.add_argument("--pilot-ack", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    cfg = BotConfig()
    cfg.validate()
    snapshot = _load_snapshot_fixture(args.snapshot_fixture) if args.snapshot_fixture else None
    return run_phase_d3_cancel_replace_pilot(
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
        linked_position_id=args.linked_position_id,
        cfg=cfg,
        order_store=OrderStore(),
        state_store=StateStore(),
        coinbase_client=CoinbaseClient() if args.allow_coinbase_poll else None,
        allow_coinbase_poll=bool(args.allow_coinbase_poll),
        allow_live_cancel=bool(args.allow_live_cancel),
        allow_live_replace=bool(args.allow_live_replace),
        pilot_ack=str(args.pilot_ack or ""),
        snapshot=snapshot,
    )


def main() -> int:
    args = parse_args()
    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
