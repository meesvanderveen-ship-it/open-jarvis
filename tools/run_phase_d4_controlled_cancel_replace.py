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

import bot.config  # noqa: F401 - loads project .env without mutating it.
from bot.coinbase_client import CoinbaseClient
from bot.live_exit_gate import D4_CONTROLLED_CANCEL_REPLACE_ACK
from bot.phase_d4_controlled_cancel_replace import run_phase_d4_controlled_cancel_replace


DEFAULT_TICKER = "BTC-USDC"
DEFAULT_CLIENT_ORDER_ID = "phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000"
DEFAULT_EXCHANGE_ORDER_ID = "daa5ef77-9967-4fb0-b0c7-4f7c0680b512"
DEFAULT_LINKED_POSITION_ID = "76310097-849e-481c-b587-ba44bc3330fe"
DEFAULT_REPLACEMENT_PRICE = "76000.00"


def _load_json_fixture(path: str) -> Dict[str, Any] | None:
    if not path:
        return None
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="D.4 controlled cancel-first replacement runner. Live only with --apply and exact ACK."
    )
    parser.add_argument("--ticker", default=DEFAULT_TICKER)
    parser.add_argument("--client-order-id", default=DEFAULT_CLIENT_ORDER_ID)
    parser.add_argument("--exchange-order-id", default=DEFAULT_EXCHANGE_ORDER_ID)
    parser.add_argument("--linked-position-id", default=DEFAULT_LINKED_POSITION_ID)
    parser.add_argument("--replacement-price", default=DEFAULT_REPLACEMENT_PRICE)
    parser.add_argument("--orders-file", default=str(PROJECT_ROOT / "state" / "open_orders.json"))
    parser.add_argument("--positions-file", default=str(PROJECT_ROOT / "state" / "positions.json"))
    parser.add_argument("--order-events-file", default=str(PROJECT_ROOT / "logs" / "order_events.jsonl"))
    parser.add_argument("--lifecycle-fixture", default="")
    parser.add_argument("--market-fixture", default="")
    parser.add_argument("--product-rules-fixture", default="")
    parser.add_argument("--post-cancel-fixture", default="")
    parser.add_argument("--resume-after-confirmed-cancel", action="store_true")
    parser.add_argument("--cancel-only-after-confirmed-cancel", action="store_true")
    parser.add_argument("--apply", action="store_true", help="Execute the live cancel/submit route if every gate passes.")
    parser.add_argument("--repair-ack", "--ack", dest="ack", default="")
    parser.add_argument("--arm-one-shot", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    apply_live = bool(args.apply)
    client_required = apply_live or not (args.lifecycle_fixture and args.market_fixture and args.product_rules_fixture)
    client = CoinbaseClient() if client_required else None
    report = run_phase_d4_controlled_cancel_replace(
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
        linked_position_id=args.linked_position_id,
        replacement_price=args.replacement_price,
        ack=args.ack,
        allow_live_cancel=apply_live,
        allow_live_replace=apply_live,
        one_shot_armed_process_local=bool(args.arm_one_shot and args.ack == D4_CONTROLLED_CANCEL_REPLACE_ACK),
        coinbase_client=client,
        orders_file=args.orders_file,
        positions_file=args.positions_file,
        order_events_file=args.order_events_file,
        lifecycle_snapshot=_load_json_fixture(args.lifecycle_fixture),
        market_snapshot=_load_json_fixture(args.market_fixture),
        product_rules=_load_json_fixture(args.product_rules_fixture),
        post_cancel_snapshot=_load_json_fixture(args.post_cancel_fixture),
        resume_after_confirmed_cancel=bool(args.resume_after_confirmed_cancel),
        cancel_only_after_confirmed_cancel=bool(args.cancel_only_after_confirmed_cancel),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if report.get("status") in {
        "d4_controlled_cancel_replace_preflight_ready",
        "d4_controlled_cancel_replace_cancel_confirmed_replacement_pending",
        "d4_controlled_cancel_replace_applied",
    } else 2


if __name__ == "__main__":
    raise SystemExit(main())
